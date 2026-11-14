"""Reviewed inventory used by the Service Operations console.

This is deliberately data, not LLM output.  Add a service only after its
owner has supplied the supervisor contract and a stable health probe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


SERVICE_CATALOG: Dict[str, Dict[str, Any]] = {
    "ticketflow-api": {
        "name": "TicketFlow API", "server": "RHEL10", "owner": "Application Team",
        "kind": "python", "health_path": "http://127.0.0.1:5000/health",
        "runbook_id": "RB-05", "auto_recovery_action": None,
        "supported_operations": ["start", "stop", "restart", "investigate"],
    },
    "notification-service": {
        "name": "Notification Service", "server": "RHEL10", "owner": "Application Team",
        "kind": "python", "health_path": "http://127.0.0.1:8080/health",
        "runbook_id": "RB-04", "auto_recovery_action": "restart_notification_service",
        "supported_operations": ["start", "stop", "restart", "investigate"],
    },
    "auth-gateway": {
        "name": "Auth Gateway", "server": "WIN2025", "owner": "Identity Team",
        "kind": "dotnet", "health_path": "http://127.0.0.1:5001/health",
        "runbook_id": "RB-03", "auto_recovery_action": "recover_auth_gateway",
        "supported_operations": ["start", "stop", "restart", "investigate"],
    },
    "audit-service": {
        "name": "Audit and DB Service", "server": "WIN2019", "owner": "Data Team",
        "kind": "dotnet/sql", "health_path": "http://127.0.0.1:8088/health",
        "runbook_id": "RB-02", "auto_recovery_action": "recover_sql_lock",
        "supported_operations": ["start", "stop", "restart", "investigate"],
    },
    "prometheus": {
        "name": "Prometheus", "server": "RHEL9", "owner": "SRE",
        "kind": "podman", "health_path": "http://127.0.0.1:9090/-/ready",
        "runbook_id": None, "auto_recovery_action": None,
        "supported_operations": [],
        "control_notice": "Enable only after migration to a named systemd/podman supervisor unit.",
    },
    "grafana": {
        "name": "Grafana", "server": "RHEL9", "owner": "SRE",
        "kind": "podman", "health_path": "http://127.0.0.1:3000/api/health",
        "runbook_id": None, "auto_recovery_action": None,
        "supported_operations": [],
        "control_notice": "Enable only after migration to a named systemd/podman supervisor unit.",
    },
    "loki": {
        "name": "Loki", "server": "RHEL9", "owner": "SRE",
        "kind": "podman", "health_path": "http://127.0.0.1:3100/ready",
        "runbook_id": None, "auto_recovery_action": None,
        "supported_operations": [],
        "control_notice": "Enable only after migration to a named systemd/podman supervisor unit.",
    },
    "tempo": {
        "name": "Tempo", "server": "RHEL9", "owner": "SRE",
        "kind": "podman", "health_path": "http://127.0.0.1:3200/ready",
        "runbook_id": None, "auto_recovery_action": None,
        "supported_operations": [],
        "control_notice": "Enable only after migration to a named systemd/podman supervisor unit.",
    },
    "alertmanager": {
        "name": "Alertmanager", "server": "RHEL9", "owner": "SRE",
        "kind": "podman", "health_path": "http://127.0.0.1:9093/-/ready",
        "runbook_id": None, "auto_recovery_action": None,
        "supported_operations": [],
        "control_notice": "Enable only after migration to a named systemd/podman supervisor unit.",
    },
}


def get_service(service_id: str) -> Optional[Dict[str, Any]]:
    service = SERVICE_CATALOG.get(service_id)
    return dict(service, id=service_id) if service else None


def list_services() -> List[Dict[str, Any]]:
    return [s for service_id in SERVICE_CATALOG if (s := get_service(service_id)) is not None]
