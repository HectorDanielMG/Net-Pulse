from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from netpulse import core


class NetPulseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        core.DB_PATH = Path(self.temp.name) / "netpulse.db"
        core.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lab_outage_opens_alert_and_incident_then_recovery_resolves_it(self) -> None:
        devices = core.load_lab()
        asyncio.run(core.run_checks([item["id"] for item in devices], "outage"))
        asyncio.run(core.run_checks([item["id"] for item in devices], "outage"))
        self.assertEqual(core.summary()["active_incidents"], 3)
        asyncio.run(core.run_checks([item["id"] for item in devices], "recovery"))
        self.assertEqual(core.summary()["active_incidents"], 0)
        self.assertEqual(core.one("SELECT status FROM devices WHERE id=?", (devices[0]["id"],))["status"], "UP")

    def test_performance_scenario_creates_warning_without_incident(self) -> None:
        devices = core.load_lab()
        asyncio.run(core.run_checks([item["id"] for item in devices], "latency"))
        self.assertGreater(core.summary()["open_alerts"], 0)
        self.assertEqual(core.summary()["active_incidents"], 0)

    def test_diagnostic_requires_existing_device(self) -> None:
        self.assertIsNone(core.diagnose("missing"))
        device = core.load_lab()[0]
        report = core.diagnose(device["id"])
        self.assertEqual(report["classification"], "sin_datos")

    def test_device_input_rejects_host_with_spaces(self) -> None:
        from netpulse.main import DeviceInput
        with self.assertRaises(ValueError):
            DeviceInput(name="Nodo", host="invalid host")

    def test_health_endpoint(self) -> None:
        from netpulse.main import app
        with TestClient(app) as client:
            response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_lab_api_generates_queryable_measurements(self) -> None:
        from netpulse.main import app
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/lab/load").status_code, 200)
            self.assertEqual(client.post("/api/lab/run", json={"scenario": "latency"}).status_code, 200)
            measurements = client.get("/api/measurements").json()
            topology = client.get("/api/topology").json()
        self.assertEqual(len(measurements), 3)
        self.assertTrue(all(item["simulated"] for item in measurements))
        self.assertEqual(len(topology["nodes"]), 3)


if __name__ == "__main__":
    unittest.main()
