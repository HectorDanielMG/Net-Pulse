"""Descubrimiento local de red sin sondeo activo.

NetPulse consulta la tabla de vecinos que el sistema operativo ya conoce. Esto
evita abrir puertos o recorrer rangos de direcciones y permite mostrar una
instantánea útil para una persona que administra su propia red.
"""
from __future__ import annotations

import ipaddress
import hashlib
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _run(*command: str) -> str:
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=2)
        return completed.stdout if completed.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


def _route() -> tuple[str | None, str | None]:
    parts = _run("ip", "route", "show", "default").split()
    if not parts:
        return None, None
    gateway = parts[2] if len(parts) > 2 and parts[0] == "default" and parts[1] == "via" else None
    interface = parts[parts.index("dev") + 1] if "dev" in parts and parts.index("dev") + 1 < len(parts) else None
    return gateway, interface


def _local_ip(interface: str | None) -> str | None:
    command = ("ip", "-o", "-4", "addr", "show", "dev", interface) if interface else ("ip", "-o", "-4", "addr", "show")
    for line in _run(*command).splitlines():
        parts = line.split()
        if "inet" in parts:
            return parts[parts.index("inet") + 1].split("/")[0]
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return None


def _neighbors(interface: str | None) -> list[dict[str, str]]:
    command = ("ip", "neigh", "show", "dev", interface) if interface else ("ip", "neigh", "show")
    devices: list[dict[str, str]] = []
    for line in _run(*command).splitlines():
        parts = line.split()
        if not parts or parts[-1] in {"FAILED", "INCOMPLETE", "NOARP"}:
            continue
        address = parts[0]
        try:
            ipaddress.ip_address(address)
        except ValueError:
            continue
        mac = parts[parts.index("lladdr") + 1] if "lladdr" in parts and parts.index("lladdr") + 1 < len(parts) else ""
        state = parts[-1]
        devices.append({"address": address, "mac": mac, "state": state})
    if devices:
        return devices

    arp = Path("/proc/net/arp")
    if not arp.exists():
        return devices
    for line in arp.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[2] != "0x0":
            devices.append({"address": parts[0], "mac": parts[3], "state": "STALE"})
    return devices


def _device(address: str, mac: str, state: str, gateway: str | None) -> dict[str, str]:
    is_router = address == gateway
    is_active = state in {"REACHABLE", "PERMANENT"}
    return {
        "key": hashlib.sha256(f"{mac}|{address}".encode()).hexdigest()[:24],
        "address": address,
        "name": "Tu router" if is_router else "Dispositivo en tu red",
        "kind": "router" if is_router else "device",
        "status": "Disponible" if is_active else "Detectado recientemente",
        "description": "Gestiona la conexión de tu red." if is_router else "Se ha comunicado recientemente con esta computadora.",
        "identifier": f"•••• {mac[-5:]}" if mac else "Identificador no disponible",
    }


def _connection_name(interface: str | None) -> str:
    if not interface:
        return "No disponible"
    normalized = interface.lower()
    if normalized.startswith(("wl", "wifi")):
        return "Wi‑Fi"
    if normalized.startswith(("en", "eth")):
        return "Cable de red"
    if normalized == "lo":
        return "Conexión local"
    return "Conexión de red"


def discover_network() -> dict:
    """Devuelve una instantánea local, sin hacer conexiones a los equipos."""
    gateway, interface = _route()
    local_ip = _local_ip(interface)
    known = _neighbors(interface)
    seen: set[str] = set()
    devices = []
    for neighbor in known:
        if neighbor["address"] == local_ip or neighbor["address"] in seen:
            continue
        seen.add(neighbor["address"])
        devices.append(_device(neighbor["address"], neighbor["mac"], neighbor["state"], gateway))
    devices.sort(key=lambda item: (item["kind"] != "router", item["address"]))
    ready = bool(local_ip and gateway)
    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "connection": "Conectado a tu red local" if ready else "No se identificó una conexión local completa",
        "connection_detail": "Tu equipo tiene una ruta de red activa." if ready else "Revisa que estés conectado a Wi‑Fi o cable y vuelve a intentarlo.",
        "local_address": local_ip or "No disponible",
        "gateway": gateway or "No disponible",
        "interface": _connection_name(interface),
        "interface_detail": interface or "No disponible",
        "devices": devices,
        "device_count": len(devices),
        "discovery_note": "Mostramos los equipos que tu computadora ya ha detectado. Los equipos en reposo pueden aparecer cuando vuelvas a actualizar.",
        "privacy_note": "La revisión se realiza en este equipo. NetPulse no abre puertos ni envía esta información a internet.",
    }
