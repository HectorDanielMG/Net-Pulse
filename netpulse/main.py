from __future__ import annotations
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from . import core, network

ROOT = Path(__file__).resolve().parents[1]
INTERVAL = max(10, int(os.getenv("MONITOR_INTERVAL_SECONDS", "30")))
last_task_error: str | None = None

class DeviceInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    host: str = Field(min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    kind: Literal["router", "switch", "server", "firewall", "other"] = "other"
    monitoring_enabled: bool = True
    simulated: bool = False
    latency_warning_ms: float = Field(default=120, gt=0, le=10000)
    loss_warning_percent: float = Field(default=5, ge=0, le=100)
    @field_validator("host")
    @classmethod
    def host_without_whitespace(cls, value: str) -> str:
        if any(char.isspace() for char in value): raise ValueError("El host no puede contener espacios.")
        return value

class MonitorInput(BaseModel):
    enabled: bool

class LabScenario(BaseModel):
    scenario: Literal["healthy", "outage", "latency", "loss", "recovery"]

@asynccontextmanager
async def lifespan(_: FastAPI):
    core.initialize()
    async def loop() -> None:
        global last_task_error
        while True:
            try: await core.run_checks()
            except Exception as exc: last_task_error = type(exc).__name__
            await asyncio.sleep(INTERVAL)
    task = asyncio.create_task(loop())
    yield
    task.cancel()

app = FastAPI(title="NetPulse", version="0.1.0", description="Observabilidad local de red con laboratorio simulado.", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

@app.get("/")
def index() -> FileResponse: return FileResponse(ROOT / "web" / "index.html")
@app.get("/healthz")
def health() -> dict: return {"status": "ok", "monitor_interval_seconds": INTERVAL, "last_monitor_run": core.summary()["last_monitor_run"], "last_task_error": last_task_error}
@app.get("/metrics", response_class=PlainTextResponse)
def prometheus() -> str: return core.metrics()
@app.get("/api/summary")
def summary() -> dict: return core.summary()
@app.get("/api/network/discovery")
def network_discovery() -> dict: return network.discover_network()
@app.get("/api/devices")
def devices() -> list[dict]: return [core.device_payload(row) for row in core.rows("SELECT * FROM devices ORDER BY name")]
@app.post("/api/devices", status_code=201)
def add_device(payload: DeviceInput) -> dict: 
    try: return core.create_device(payload.model_dump())
    except Exception as exc: raise HTTPException(409, "No se pudo registrar el dispositivo; el nombre debe ser único.") from exc
@app.patch("/api/devices/{device_id}/monitoring")
def monitoring(device_id: str, payload: MonitorInput) -> dict:
    result = core.set_monitoring(device_id, payload.enabled)
    if not result: raise HTTPException(404, "Dispositivo no encontrado")
    return result
@app.post("/api/devices/{device_id}/check")
async def check(device_id: str) -> list[dict]:
    if not core.one("SELECT 1 FROM devices WHERE id=?", (device_id,)): raise HTTPException(404, "Dispositivo no encontrado")
    return await core.run_checks([device_id])
@app.get("/api/measurements")
def measurements(device_id: str | None = None, limit: int = Query(80, ge=1, le=500)) -> list[dict]: return core.history(device_id, limit)
@app.get("/api/alerts")
def alerts() -> list[dict]: return [dict(row) for row in core.rows("SELECT a.*,d.name AS device_name FROM alerts a JOIN devices d ON d.id=a.device_id ORDER BY a.updated_at DESC")]
@app.get("/api/incidents")
def incidents() -> list[dict]: return [dict(row) for row in core.rows("SELECT i.*,d.name AS device_name FROM incidents i JOIN devices d ON d.id=i.device_id ORDER BY i.opened_at DESC")]
@app.get("/api/events")
def events() -> list[dict]: return [dict(row) for row in core.rows("SELECT e.*,d.name AS device_name FROM events e LEFT JOIN devices d ON d.id=e.device_id ORDER BY e.created_at DESC LIMIT 50")]
@app.get("/api/topology")
def get_topology() -> dict: return core.topology()
@app.get("/api/diagnostics/{device_id}")
def diagnostics(device_id: str) -> dict:
    result = core.diagnose(device_id)
    if not result: raise HTTPException(404, "Dispositivo no encontrado")
    return result
@app.post("/api/lab/load")
def lab_load() -> list[dict]: return core.load_lab()
@app.post("/api/lab/run")
async def lab_run(payload: LabScenario) -> list[dict]:
    devices = core.load_lab()
    return await core.run_checks([device["id"] for device in devices], payload.scenario)
@app.delete("/api/lab")
def lab_clear() -> dict: core.clear_lab(); return {"status": "cleared"}
