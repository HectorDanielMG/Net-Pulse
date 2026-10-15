"""Persistencia, monitor y reglas explicables de NetPulse.

Las comprobaciones TCP se realizan exclusivamente a dispositivos registrados. Los
dispositivos de laboratorio producen datos etiquetados como simulados y nunca
generan tráfico de red.
"""
from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
import time
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any
from uuid import uuid4

DB_PATH = Path(os.getenv("DATABASE_PATH", "netpulse.db"))
TCP_TIMEOUT = max(0.2, float(os.getenv("TCP_TIMEOUT_SECONDS", "1.5")))
MAX_CONCURRENCY = max(1, int(os.getenv("MAX_CONCURRENT_CHECKS", "8")))


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con


def initialize() -> None:
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL, port INTEGER,
          kind TEXT NOT NULL, monitoring_enabled INTEGER NOT NULL DEFAULT 1,
          simulated INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'UNKNOWN',
          latency_warning_ms REAL NOT NULL DEFAULT 120, loss_warning_percent REAL NOT NULL DEFAULT 5,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS devices_name_unique ON devices(name);
        CREATE TABLE IF NOT EXISTS links (
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          target_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          label TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS measurements (
          id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          measured_at TEXT NOT NULL, check_type TEXT NOT NULL, success INTEGER NOT NULL,
          latency_ms REAL, packets_sent INTEGER NOT NULL DEFAULT 1, packets_received INTEGER NOT NULL DEFAULT 0,
          loss_percent REAL NOT NULL DEFAULT 100, error TEXT, simulated INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS measurements_device_time ON measurements(device_id, measured_at DESC);
        CREATE TABLE IF NOT EXISTS alerts (
          id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          rule_code TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(device_id, rule_code, state)
        );
        CREATE TABLE IF NOT EXISTS incidents (
          id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
          title TEXT NOT NULL, state TEXT NOT NULL, opened_at TEXT NOT NULL, resolved_at TEXT, note TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY, device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
          category TEXT NOT NULL, message TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS network_device_preferences (
          device_key TEXT PRIMARY KEY, alias TEXT NOT NULL DEFAULT '', known INTEGER NOT NULL DEFAULT 0,
          notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        """)
        con.execute("INSERT OR IGNORE INTO app_state(key,value,updated_at) VALUES('last_monitor_run','',?)", (stamp(),))


def event(con: sqlite3.Connection, device_id: str | None, category: str, message: str, simulated: bool = False) -> None:
    con.execute("INSERT INTO events(id,device_id,category,message,simulated,created_at) VALUES(?,?,?,?,?,?)", (str(uuid4()), device_id, category, message, int(simulated), stamp()))


def rows(query: str, values: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    with db() as con:
        return con.execute(query, values).fetchall()


def one(query: str, values: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    with db() as con:
        return con.execute(query, values).fetchone()


def device_payload(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["monitoring_enabled"] = bool(result["monitoring_enabled"])
    result["simulated"] = bool(result["simulated"])
    return result


def network_device_preferences() -> dict[str, dict[str, Any]]:
    return {
        row["device_key"]: {"alias": row["alias"], "known": bool(row["known"]), "notes": row["notes"]}
        for row in rows("SELECT device_key,alias,known,notes FROM network_device_preferences")
    }


def save_network_device_preference(device_key: str, alias: str, known: bool, notes: str) -> dict[str, Any]:
    with db() as con:
        con.execute("""INSERT INTO network_device_preferences(device_key,alias,known,notes,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(device_key) DO UPDATE SET alias=excluded.alias,known=excluded.known,
        notes=excluded.notes,updated_at=excluded.updated_at""", (device_key, alias.strip(), int(known), notes.strip(), stamp()))
    return {"alias": alias.strip(), "known": known, "notes": notes.strip()}


def create_device(data: dict[str, Any]) -> dict[str, Any]:
    device_id = str(uuid4())
    with db() as con:
        con.execute("""INSERT INTO devices(id,name,host,port,kind,monitoring_enabled,simulated,latency_warning_ms,loss_warning_percent,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (device_id, data["name"].strip(), data["host"].strip(), data.get("port"), data["kind"], int(data.get("monitoring_enabled", True)), int(data.get("simulated", False)), data.get("latency_warning_ms", 120), data.get("loss_warning_percent", 5), stamp(), stamp()))
        event(con, device_id, "device", "Dispositivo registrado para monitoreo.", bool(data.get("simulated", False)))
        return device_payload(con.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone())


def set_monitoring(device_id: str, enabled: bool) -> dict[str, Any] | None:
    with db() as con:
        row = con.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if not row:
            return None
        con.execute("UPDATE devices SET monitoring_enabled=?, status=?, updated_at=? WHERE id=?", (int(enabled), "UNKNOWN" if not enabled else row["status"], stamp(), device_id))
        event(con, device_id, "monitor", "Monitoreo activado." if enabled else "Monitoreo pausado.", bool(row["simulated"]))
        return device_payload(con.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone())


def _record_measurement(device_id: str, success: bool, latency: float | None, loss: float, error: str | None, simulated: bool, check_type: str = "tcp") -> dict[str, Any]:
    with db() as con:
        con.execute("""INSERT INTO measurements(id,device_id,measured_at,check_type,success,latency_ms,packets_sent,packets_received,loss_percent,error,simulated)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (str(uuid4()), device_id, stamp(), check_type, int(success), latency, 1, 1 if success else 0, loss, error, int(simulated)))
        measurement = con.execute("SELECT * FROM measurements WHERE device_id=? ORDER BY measured_at DESC, rowid DESC LIMIT 1", (device_id,)).fetchone()
        _evaluate(con, con.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone(), measurement)
    return dict(measurement)


def _open_alert(con: sqlite3.Connection, device: sqlite3.Row, rule: str, severity: str, message: str) -> None:
    existing = con.execute("SELECT id FROM alerts WHERE device_id=? AND rule_code=? AND state='open'", (device["id"], rule)).fetchone()
    if not existing:
        con.execute("INSERT INTO alerts(id,device_id,rule_code,severity,message,state,created_at,updated_at) VALUES(?,?,?,?,?,'open',?,?)", (str(uuid4()), device["id"], rule, severity, message, stamp(), stamp()))
        event(con, device["id"], "alert", message, bool(device["simulated"]))


def _close_alert(con: sqlite3.Connection, device_id: str, rule: str) -> None:
    con.execute("UPDATE alerts SET state='resolved',updated_at=? WHERE device_id=? AND rule_code=? AND state='open'", (stamp(), device_id, rule))


def _evaluate(con: sqlite3.Connection, device: sqlite3.Row, measurement: sqlite3.Row) -> None:
    recent = con.execute("SELECT * FROM measurements WHERE device_id=? ORDER BY measured_at DESC, rowid DESC LIMIT 2", (device["id"],)).fetchall()
    failures = len(recent) == 2 and all(not item["success"] for item in recent)
    degraded = bool(measurement["success"] and ((measurement["latency_ms"] or 0) > device["latency_warning_ms"] or measurement["loss_percent"] > device["loss_warning_percent"]))
    previous = device["status"]
    status = "DOWN" if failures else "DEGRADED" if degraded else "UP" if measurement["success"] else "UNKNOWN"
    con.execute("UPDATE devices SET status=?,updated_at=? WHERE id=?", (status, stamp(), device["id"]))
    if failures:
        _open_alert(con, device, "connectivity", "CRITICAL", "Dos comprobaciones consecutivas fallaron; conectividad no confirmada.")
        open_incident = con.execute("SELECT id FROM incidents WHERE device_id=? AND state='open'", (device["id"],)).fetchone()
        if not open_incident:
            con.execute("INSERT INTO incidents(id,device_id,title,state,opened_at,note) VALUES(?,?,?,'open',?,?)", (str(uuid4()), device["id"], f"Conectividad degradada: {device['name']}", stamp(), "Confirmado tras dos comprobaciones fallidas."))
    else:
        _close_alert(con, device["id"], "connectivity")
        if previous == "DOWN" and measurement["success"]:
            con.execute("UPDATE incidents SET state='resolved',resolved_at=?,note=? WHERE device_id=? AND state='open'", (stamp(), "Resuelto después de una comprobación exitosa.", device["id"]))
            event(con, device["id"], "recovery", "El dispositivo respondió nuevamente.", bool(device["simulated"]))
    if degraded:
        _open_alert(con, device, "performance", "WARNING", "Latencia o pérdida supera el umbral configurado.")
    else:
        _close_alert(con, device["id"], "performance")


async def tcp_check(device: sqlite3.Row) -> dict[str, Any]:
    if not device["port"]:
        return _record_measurement(device["id"], False, None, 100, "El dispositivo no tiene puerto TCP configurado.", False)
    began = time.perf_counter()
    try:
        writer = None
        _, writer = await asyncio.wait_for(asyncio.open_connection(device["host"], device["port"]), timeout=TCP_TIMEOUT)
        writer.close()
        await writer.wait_closed()
        return _record_measurement(device["id"], True, round((time.perf_counter() - began) * 1000, 2), 0, None, False)
    except (asyncio.TimeoutError, OSError) as exc:
        return _record_measurement(device["id"], False, None, 100, f"TCP no disponible: {type(exc).__name__}", False)


def simulated_check(device: sqlite3.Row, scenario: str) -> dict[str, Any]:
    mapping = {
        "healthy": (True, 18.0, 0.0, None), "latency": (True, max(float(device["latency_warning_ms"]) + 65, 185), 0.0, None),
        "loss": (True, 55.0, max(float(device["loss_warning_percent"]) + 12, 20), None),
        "outage": (False, None, 100.0, "Escenario de laboratorio: caída simulada."),
        "recovery": (True, 22.0, 0.0, None),
    }
    success, latency, loss, error = mapping[scenario]
    return _record_measurement(device["id"], success, latency, loss, error, True, "lab")


async def run_checks(device_ids: list[str] | None = None, scenario: str = "healthy") -> list[dict[str, Any]]:
    query, values = "SELECT * FROM devices WHERE monitoring_enabled=1", ()
    if device_ids:
        marks = ",".join("?" for _ in device_ids)
        query += f" AND id IN ({marks})"; values = tuple(device_ids)
    devices = rows(query, values)
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    async def check(device: sqlite3.Row) -> dict[str, Any]:
        async with semaphore:
            return simulated_check(device, scenario) if device["simulated"] else await tcp_check(device)
    results = await asyncio.gather(*(check(device) for device in devices), return_exceptions=True)
    successful = [item for item in results if isinstance(item, dict)]
    with db() as con:
        con.execute("UPDATE app_state SET value=?,updated_at=? WHERE key='last_monitor_run'", (stamp(), stamp()))
    return successful


def load_lab() -> list[dict[str, Any]]:
    with db() as con:
        existing = con.execute("SELECT * FROM devices WHERE simulated=1 ORDER BY name").fetchall()
        if existing:
            return [device_payload(row) for row in existing]
    specs = [("LAB-RTR-01", "router", "192.0.2.1"), ("LAB-SW-01", "switch", "192.0.2.2"), ("LAB-SRV-01", "server", "192.0.2.10")]
    devices = [create_device({"name": name, "kind": kind, "host": host, "simulated": True, "latency_warning_ms": 120, "loss_warning_percent": 5}) for name, kind, host in specs]
    with db() as con:
        for source, target, label in ((devices[0], devices[1], "enlace de laboratorio"), (devices[1], devices[2], "VLAN de laboratorio")):
            con.execute("INSERT INTO links(id,source_id,target_id,label,provenance,created_at) VALUES(?,?,?,?,?,?)", (str(uuid4()), source["id"], target["id"], label, "laboratory", stamp()))
        event(con, None, "lab", "Topología de laboratorio cargada. Todos sus datos son simulados.", True)
    return devices


def clear_lab() -> None:
    with db() as con:
        con.execute("DELETE FROM devices WHERE simulated=1")
        event(con, None, "lab", "Datos de laboratorio eliminados; los dispositivos reales no fueron afectados.", True)


def summary() -> dict[str, Any]:
    device_rows = rows("SELECT * FROM devices")
    latest = rows("SELECT latency_ms,loss_percent,success FROM measurements WHERE measured_at>=?", ((now() - timedelta(hours=24)).isoformat(),))
    valid_latencies = [row["latency_ms"] for row in latest if row["success"] and row["latency_ms"] is not None]
    state = one("SELECT value,updated_at FROM app_state WHERE key='last_monitor_run'")
    return {"devices": len(device_rows), "up": sum(row["status"] == "UP" for row in device_rows), "down": sum(row["status"] == "DOWN" for row in device_rows), "degraded": sum(row["status"] == "DEGRADED" for row in device_rows), "unknown": sum(row["status"] == "UNKNOWN" for row in device_rows), "active_incidents": one("SELECT COUNT(*) count FROM incidents WHERE state='open'")["count"], "open_alerts": one("SELECT COUNT(*) count FROM alerts WHERE state='open'")["count"], "average_latency_ms": round(sum(valid_latencies) / len(valid_latencies), 1) if valid_latencies else None, "packet_loss_percent": round(sum(row["loss_percent"] for row in latest) / len(latest), 1) if latest else None, "availability_percent": round(100 * sum(row["success"] for row in latest) / len(latest), 1) if latest else None, "last_monitor_run": state["value"] if state else None, "has_data": bool(latest)}


def history(device_id: str | None = None, limit: int = 120) -> list[dict[str, Any]]:
    query = "SELECT m.*,d.name AS device_name FROM measurements m JOIN devices d ON d.id=m.device_id"
    values: tuple[Any, ...] = ()
    if device_id: query += " WHERE m.device_id=?"; values = (device_id,)
    return [dict(row) for row in rows(query + " ORDER BY m.measured_at DESC, m.rowid DESC LIMIT ?", values + (limit,))]


def topology() -> dict[str, Any]:
    return {"nodes": [device_payload(row) for row in rows("SELECT * FROM devices ORDER BY name")], "links": [dict(row) for row in rows("SELECT * FROM links ORDER BY created_at")]}


def diagnose(device_id: str) -> dict[str, Any] | None:
    device = one("SELECT * FROM devices WHERE id=?", (device_id,))
    if not device: return None
    recent = history(device_id, 10)
    if not recent: return {"device": device_payload(device), "classification": "sin_datos", "recommendation": "Ejecute una comprobación autorizada o use el laboratorio; no hay datos para diagnosticar."}
    failures = [item for item in recent if not item["success"]]
    latest = recent[0]
    if len(recent) >= 2 and len(failures) >= 2:
        classification, recommendation = "conectividad_no_confirmada", "Dos o más comprobaciones fallaron. Verifique alimentación, ruta y filtrado TCP; no se confirma una causa raíz."
    elif latest["loss_percent"] > device["loss_warning_percent"]:
        classification, recommendation = "perdida_elevada", "La pérdida supera el umbral. Revise errores de interfaz, congestión y el tramo de red asociado."
    elif latest["latency_ms"] and latest["latency_ms"] > device["latency_warning_ms"]:
        classification, recommendation = "latencia_elevada", "La latencia supera el umbral. Compare con el historial y revise saturación o cambios de ruta."
    else:
        classification, recommendation = "sin_anomalia_observada", "No se detectó una condición de alerta en las mediciones recientes; esto no confirma salud de todos los servicios."
    return {"device": device_payload(device), "classification": classification, "recommendation": recommendation, "measurements_considered": len(recent), "latest": latest}


def metrics() -> str:
    data = summary()
    values = [("netpulse_devices_total", data["devices"]), ("netpulse_alerts_open", data["open_alerts"]), ("netpulse_incidents_open", data["active_incidents"]), ("netpulse_measurements_available", 1 if data["has_data"] else 0)]
    return "\n".join(["# HELP netpulse_devices_total Dispositivos registrados.", "# TYPE netpulse_devices_total gauge"] + [f"{key} {value}" for key, value in values]) + "\n"
