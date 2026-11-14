"""Server-side allowlist for AIST remediation operations.

The model may recommend an action, but it must never supply an executable
command.  This catalog is the narrow trust boundary between an LLM response
and a machine-changing tool call.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional


REMEDIATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "recover_auth_gateway": {
        "title": "Recover AuthGateway on Windows Server 2025",
        "target_server": "WIN2025",
        "command": "Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/v1/chaos/recover' -Method POST",
        "verification": "(Test-NetConnection -ComputerName 127.0.0.1 -Port 5001 -WarningAction SilentlyContinue).TcpTestSucceeded",
        "action_type": "powershell_recovery",
        "blast_radius": "Low - restarts the AuthGateway worker only",
        "requires_approval": True,
        "runbook_id": "RB-03",
    },
    "recover_sql_lock": {
        "title": "Recover the simulated SQL lock on Windows Server 2019",
        "target_server": "WIN2019",
        "command": "Invoke-RestMethod -Uri 'http://127.0.0.1:8088/api/v1/chaos/recover' -Method POST",
        "verification": "(Test-NetConnection -ComputerName 127.0.0.1 -Port 8088 -WarningAction SilentlyContinue).TcpTestSucceeded",
        "action_type": "powershell_recovery",
        "blast_radius": "Medium - releases a simulated database lock; production KILL statements require DBA approval",
        "requires_approval": True,
        "runbook_id": "RB-02",
    },
    "recover_notification_queue": {
        "title": "Recover notification queue processing on RHEL 10",
        "target_server": "RHEL10",
        "command": "curl --fail --silent --show-error -X POST http://127.0.0.1:8080/api/v1/chaos/recover",
        "verification": "curl --fail --silent http://127.0.0.1:8080/health",
        "action_type": "queue_recovery",
        "blast_radius": "Low - resets the AIST notification-service lab backlog",
        "requires_approval": True,
        "runbook_id": "RB-04",
    },
    "restart_notification_service": {
        "title": "Restart Notification Service on RHEL 10",
        "target_server": "RHEL10",
        "command": "nohup /opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py </dev/null >/opt/aist/notification-service/service.log 2>&1 &",
        "verification": "curl --fail --silent http://127.0.0.1:8080/health",
        "action_type": "restart_service",
        "blast_radius": "Low - restarts only the Notification Service consumer",
        "requires_approval": True,
        "runbook_id": "RB-04",
    },
    "recover_ticketflow_api": {
        "title": "Recover TicketFlow API on RHEL 10",
        "target_server": "RHEL10",
        "command": "curl --fail --silent --show-error -X POST http://127.0.0.1:5000/api/v1/chaos/recover",
        "verification": "curl --fail --silent http://127.0.0.1:5000/health",
        "action_type": "api_recovery",
        "blast_radius": "Low - clears injected latency and error simulation flags",
        "requires_approval": True,
        "runbook_id": "RB-05",
    },
    "stop_synthetic_cpu_stress_rhel10": {
        "title": "Stop the AIST synthetic CPU stress process on RHEL 10",
        "target_server": "RHEL10",
        "command": "pkill -9 -f 'sum(' || pkill -9 -f 'aist_cpu_burner' || true",
        "verification": "uptime",
        "action_type": "synthetic_workload_cleanup",
        "blast_radius": "Low - only targets the known AIST chaos workload",
        "requires_approval": True,
        "runbook_id": "RB-01",
    },
    "stop_synthetic_cpu_stress_rhel9": {
        "title": "Stop the AIST synthetic CPU stress process on RHEL 9",
        "target_server": "RHEL9",
        "command": "pkill -9 -f 'sum(' || pkill -9 -f 'aist_cpu_burner' || true",
        "verification": "uptime",
        "action_type": "synthetic_workload_cleanup",
        "blast_radius": "Low - only targets the known AIST chaos workload",
        "requires_approval": True,
        "runbook_id": "RB-01",
    },
}


def get_remediation(action_id: str) -> Optional[Dict[str, Any]]:
    """Return a copy so request processing cannot mutate the catalog."""
    action = REMEDIATION_CATALOG.get(action_id)
    if action is None:
        return None
    result = deepcopy(action)
    result["id"] = action_id
    return result


def public_remediation(action_id: str) -> Optional[Dict[str, Any]]:
    """Return the UI-safe metadata; execution commands stay server-side."""
    action = get_remediation(action_id)
    if action is None:
        return None
    action.pop("command", None)
    action.pop("verification", None)
    return action
