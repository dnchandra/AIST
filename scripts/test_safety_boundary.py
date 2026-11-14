"""Offline regression checks for the AIST control-plane safety boundary.

This script deliberately does not contact VMware, Linux, Windows, or Ollama.
Run it after changing the API models or remediation catalog:
    .\\.venv\\Scripts\\python.exe scripts\\test_safety_boundary.py
"""

import os
import sys

from fastapi.testclient import TestClient


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "ai-triage", "webui", "backend", "app"))

from main import app  # noqa: E402


client = TestClient(app)


def expect(status_code: int, response, name: str) -> None:
    assert response.status_code == status_code, f"{name}: expected {status_code}, got {response.status_code}: {response.text}"


expect(
    404,
    client.post("/api/v1/copilot/execute_action", json={"action_id": "not-real", "approved": True}),
    "unknown remediation",
)
expect(
    409,
    client.post("/api/v1/copilot/execute_action", json={"action_id": "recover_auth_gateway", "approved": False}),
    "missing human approval",
)
expect(
    422,
    client.post("/api/v1/services/control", json={"server": "RHEL10", "service": "not-a-service", "action": "restart"}),
    "unmanaged service",
)
expect(
    422,
    client.post("/api/v1/chaos/trigger", json={"scenario": "not-a-scenario", "target_server": "RHEL10"}),
    "unknown chaos scenario",
)
expect(
    400,
    client.options(
        "/api/v1/copilot/query",
        headers={"Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST"},
    ),
    "untrusted browser origin",
)
services = client.get("/api/v1/services")
expect(200, services, "service inventory")
assert {"ticketflow-api", "notification-service", "auth-gateway", "audit-service"}.issubset({item["id"] for item in services.json()})
metrics = client.get("/metrics")
expect(200, metrics, "controller metrics")
assert "aist_service_operations_total" in metrics.text

print("Safety boundary API checks passed")
