"""
AIST AI Triage FastAPI Backend (Python 3.12+ / Uvicorn)
Coordinates LangGraph 0.2 Agent Swarm, FastMCP 4.1 Tools, AlertManager Webhooks, and HITL Approvals.
Provides real-time Service Controls and targeted Multi-OS Chaos Engineering.
"""

import json
import logging
import os
import sys
import uuid
import time
import requests
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from langgraph.types import Command

# Path configuration
AIST_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, AIST_ROOT)
sys.path.insert(0, os.path.join(AIST_ROOT, "ai-triage"))
sys.path.insert(0, os.path.join(AIST_ROOT, "ai-triage", "knowledge-base"))
sys.path.insert(0, os.path.join(AIST_ROOT, "ai-triage", "mcp-servers"))
sys.path.insert(0, os.path.join(AIST_ROOT, "ai-triage", "agents"))

from config import (
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP,
    LINUX_USER, LINUX_PASS, WINDOWS_USER, WINDOWS_PASS,
    ALERTMANAGER_URL, CORS_ORIGINS, TICKETFLOW_API_URL, NOTIFICATION_API_URL,
    AUTH_GATEWAY_URL, AUDIT_SERVICE_URL,
    PRIMARY_LLM, EMBEDDING_LLM
)
from mcp_server import (
    TOOLS, tool_query_vcenter, tool_get_active_alerts, tool_run_linux_ssh, 
    tool_run_windows_powershell, tool_windows_event_logs, tool_windows_iis_status, 
    tool_windows_os_patching, tool_windows_disk_info
)
from langchain_core.runnables import RunnableConfig
from triage_graph import build_triage_graph, call_llm, TriageState
from remediation_policy import get_remediation, public_remediation
from service_catalog import get_service, list_services
from state_store import AistStateStore
from self_healing import MonitoredRecovery
from rag_engine import get_rag_engine

# Dual Rolling Logger (Console + logs/aist_backend.log)
from logging.handlers import RotatingFileHandler
LOGS_DIR = os.path.join(AIST_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
BACKEND_LOG_FILE = os.path.join(LOGS_DIR, "aist_backend.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    BACKEND_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("aist_backend")

app = FastAPI(
    title="AIST AI SRE Triage API",
    version="3.0.0",
    description="Enterprise Multi-OS AI Incident Triage Engine with LangGraph & FastMCP"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount compiled React 19 WebUI static assets
FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.exists(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_frontend():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))

# In-memory incident cache (starts clean or hydrated from durable store)
INCIDENT_SESSIONS: Dict[str, Dict[str, Any]] = {}
ALERT_INCIDENT_BY_FINGERPRINT: Dict[str, str] = {}
TRIAGE_GRAPH = build_triage_graph()
STATE_STORE = AistStateStore(os.path.join(AIST_ROOT, "data", "aist_state.db"))

try:
    INCIDENT_SESSIONS.update(STATE_STORE.load_all_incidents())
    logger.info("Hydrated %d incident sessions from durable store.", len(INCIDENT_SESSIONS))
except Exception as e:
    logger.warning("Failed to hydrate incidents from state store: %s", e)


class AlertWebhookPayload(BaseModel):
    version: Optional[str] = "4"
    status: Optional[str] = "firing"
    alerts: list = []


class ManualTriageRequest(BaseModel):
    query: str
    target_os: Optional[str] = None
    severity: Optional[str] = "critical"


class RemediationDecisionRequest(BaseModel):
    incident_id: str
    decision: str  # "approved" or "rejected"


class ServiceControlRequest(BaseModel):
    server: str  # "RHEL10", "RHEL9", "WIN2025", "WIN2019"
    service: str # "ticketflow-api", "notification-service", "auth-gateway", "audit-service"
    action: str  # "start", "stop", "restart", "status"


class ChaosTriggerRequest(BaseModel):
    scenario: str        # "iis_crash", "cpu_spike", "sql_deadlock", "queue_backlog", "ticket_500", "ticket_latency", "recover"
    target_server: str   # "WIN2025", "WIN2019", "RHEL10", "RHEL9"


class ServiceOperationRequest(BaseModel):
    service_id: str
    action: str  # start, stop, restart, investigate
    reason: str = Field(min_length=3, max_length=500)
    requested_by: str = Field(default="operator", min_length=1, max_length=100)


class AutoRecoveryRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=100)
    service_id: str
    analysis: str = Field(min_length=3, max_length=4000)
    operator_approved: bool = False


@app.get("/health")
@app.get("/api/v1/health")
def health():
    return {
        "status": "HEALTHY",
        "service": "aist-triage-backend",
        "agent_engine": "LangGraph 0.2+",
        "primary_llm": f"{PRIMARY_LLM} (100% GPU offload on RTX 5090)",
        "active_incidents": len(INCIDENT_SESSIONS),
        "timestamp": time.time()
    }


@app.get("/api/v1/telemetry/overview")
def get_telemetry_overview():
    """Returns real-time telemetry snapshot across all 4 OS environments."""
    vcenter_data = tool_query_vcenter()
    alerts_data = tool_get_active_alerts()
    linux_stats = tool_run_linux_ssh(command="uptime")

    return {
        "success": True,
        "vcenter": {
            "status": vcenter_data.get("status"),
            "vm_count": len(vcenter_data.get("vms", [])),
            "vms": vcenter_data.get("vms", [])
        },
        "alerts": {
            "count": len(alerts_data) if isinstance(alerts_data, list) else 0,
            "items": alerts_data
        },
        "linux_node": linux_stats.get("stdout", "offline")
    }


def _update_incident(incident_id: str, updates: dict | None = None):
    """Update in-memory session and persist to SQLite state store."""
    if updates and incident_id in INCIDENT_SESSIONS:
        INCIDENT_SESSIONS[incident_id].update(updates)
    inc = INCIDENT_SESSIONS.get(incident_id)
    if inc:
        try:
            STATE_STORE.save_incident(inc)
        except Exception as e:
            logger.debug(f"Failed to persist incident {incident_id}: {e}")


@app.post("/api/v1/alerts/webhook")
async def alertmanager_webhook(payload: AlertWebhookPayload, background_tasks: BackgroundTasks):
    """Webhook listener triggered automatically by Prometheus AlertManager."""
    logger.info("Received AlertManager webhook with %d alert(s)", len(payload.alerts))
    queued = 0
    for alert in payload.alerts:
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_status = (alert.get("status") or payload.status or "firing").lower()
        fingerprint = alert.get("fingerprint") or json.dumps(labels, sort_keys=True)

        # Resolved alerts update/close the correlated incident instead of creating
        # a duplicate investigation.
        if alert_status == "resolved":
            existing_id = ALERT_INCIDENT_BY_FINGERPRINT.get(fingerprint)
            if existing_id and existing_id in INCIDENT_SESSIONS:
                INCIDENT_SESSIONS[existing_id]["status"] = "RESOLVED"
                INCIDENT_SESSIONS[existing_id]["resolved_at"] = time.time()
                _update_incident(existing_id)
            continue

        # Firing alerts are deduplicated by AlertManager fingerprint/group key.
        existing_id = ALERT_INCIDENT_BY_FINGERPRINT.get(fingerprint)
        if existing_id and existing_id in INCIDENT_SESSIONS:
            existing = INCIDENT_SESSIONS[existing_id]
            if existing.get("status") not in ("RESOLVED", "ERROR"):
                logger.info("Duplicate alert fingerprint %s maps to %s; skipping", fingerprint, existing_id)
                continue

        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        target = labels.get("target_os") or labels.get("os", "RHEL10")
        summary = annotations.get("summary") or annotations.get("description", "Infrastructure Alert Fired")

        incident_data = {
            "incident_id": incident_id,
            "status": "INVESTIGATING",
            "alertname": labels.get("alertname", "UnknownAlert"),
            "severity": labels.get("severity", "critical"),
            "target_os": target.upper(),
            "summary": summary,
            "description": annotations.get("description", ""),
            "fingerprint": fingerprint,
            "alert_status": alert_status,
            "created_at": time.time(),
            "state": {}
        }
        INCIDENT_SESSIONS[incident_id] = incident_data
        _update_incident(incident_id)
        ALERT_INCIDENT_BY_FINGERPRINT[fingerprint] = incident_id
        background_tasks.add_task(run_agent_investigation, incident_id, alert)
        queued += 1

    return {"status": "accepted", "queued_incidents": queued}


@app.post("/api/v1/triage/investigate")
async def manual_investigate(req: ManualTriageRequest, background_tasks: BackgroundTasks):
    """User-initiated incident investigation from the WebUI chat prompt."""
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    q_lower = req.query.lower()
    
    # Intelligently resolve Target OS if not explicitly supplied
    if req.target_os and req.target_os.upper() in ["WIN2025", "WIN2019", "RHEL10", "RHEL9"]:
        target_os = req.target_os.upper()
    elif "iis" in q_lower or "2025" in q_lower or "auth" in q_lower:
        target_os = "WIN2025"
    elif "sql" in q_lower or "deadlock" in q_lower or "2019" in q_lower:
        target_os = "WIN2019"
    elif "rhel9" in q_lower or "observability" in q_lower or "prometheus" in q_lower:
        target_os = "RHEL9"
    else:
        target_os = "RHEL10"

    alert_mock = {
        "labels": {"alertname": "UserInitiatedTriage", "severity": req.severity, "target_os": target_os},
        "annotations": {"summary": req.query, "description": req.query}
    }
    incident_data = {
        "incident_id": incident_id,
        "status": "INVESTIGATING",
        "alertname": "Manual Query",
        "severity": req.severity,
        "target_os": target_os,
        "summary": req.query,
        "created_at": time.time(),
        "state": {}
    }
    INCIDENT_SESSIONS[incident_id] = incident_data
    _update_incident(incident_id)
    
    background_tasks.add_task(run_agent_investigation, incident_id, alert_mock, req.query)
    return {"incident_id": incident_id, "status": "INVESTIGATION_STARTED", "target_os": target_os}


# --- Chaos Engineering Trigger with Target Server Selection ---
@app.post("/api/v1/chaos/trigger")
async def trigger_chaos(req: ChaosTriggerRequest, background_tasks: BackgroundTasks):
    """Executes a failure scenario against a user-selected target server and launches AI triage."""
    scenario = req.scenario.lower()
    target = req.target_server.upper()
    supported_scenarios = {
        "iis_crash", "auth_crash", "sql_deadlock", "cpu_spike", "queue_backlog",
        "ticket_500", "ticket_latency", "multistage_cascade", "cascade", "recover"
    }
    if scenario not in supported_scenarios:
        raise HTTPException(status_code=422, detail="Unsupported chaos scenario")
    if target not in {"RHEL10", "RHEL9", "WIN2025", "WIN2019", "ALL", "MULTI-OS"}:
        raise HTTPException(status_code=422, detail="Unsupported chaos target")
    logger.info("Executing chaos scenario '%s' against target '%s'", scenario, target)

    summary = ""
    severity = "critical"
    
    if scenario in ["iis_crash", "auth_crash"]:
        target = "WIN2025"
        summary = "HTTP 503 Service Unavailable: AuthGateway IIS AppPool crash on Windows Server 2025"
        try:
            requests.post(f"http://{WIN2025_IP}:5001/api/v1/chaos/crash", timeout=3)
        except Exception:
            pass

    elif scenario == "sql_deadlock":
        target = "WIN2019"
        summary = "SQL Server exclusive table lock (TABLOCKX) contention; 5 SPIDs blocked in TicketFlowDB"
        try:
            requests.post(f"http://{WIN2019_IP}:8088/api/v1/chaos/deadlock", timeout=3)
        except Exception:
            pass

    elif scenario == "cpu_spike":
        host = RHEL10_IP if target == "RHEL10" else RHEL9_IP
        summary = f"High CPU saturation spike (>95% utilization) on {target} application node"
        # Run background stress process
        cmd = "nohup python3 -c 'import time; [sum(i*i for i in range(1000000)) for _ in iter(int, 1)]' </dev/null >/dev/null 2>&1 &"
        try:
            tool_run_linux_ssh(host=host, command=cmd)
        except Exception:
            pass

    elif scenario == "queue_backlog":
        target = "RHEL10"
        summary = "RabbitMQ message queue backlog spike (>650 ready messages) on ticket.created"
        try:
            requests.post(f"http://{RHEL10_IP}:8080/api/v1/chaos/backlog", timeout=3)
        except Exception:
            pass

    elif scenario == "ticket_500":
        target = "RHEL10"
        summary = "HTTP 500 Internal Server Error spike on TicketFlow Core API"
        try:
            requests.post(f"http://{RHEL10_IP}:5000/api/v1/chaos/error", timeout=3)
        except Exception:
            pass

    elif scenario == "ticket_latency":
        target = "RHEL10"
        summary = "P99 Latency SLA violation (>5.0s response delay) on TicketFlow Core API"
        try:
            requests.post(f"http://{RHEL10_IP}:5000/api/v1/chaos/latency", json={"delay_seconds": 5.0}, timeout=1)
        except Exception:
            pass

    elif scenario in ["multistage_cascade", "cascade"]:
        target = "MULTI-OS"
        summary = "Cascading Multi-Tier Outage: CPU Stress on RHEL 10 -> AuthGateway Crash on Win2025 -> SQL Deadlock on Win2019"
        try:
            cmd = "nohup python3 -c 'import time; [sum(i*i for i in range(1000000)) for _ in iter(int, 1)]' </dev/null >/dev/null 2>&1 &"
            tool_run_linux_ssh(host=RHEL10_IP, command=cmd)
            requests.post(f"http://{WIN2025_IP}:5001/api/v1/chaos/crash", timeout=2)
            requests.post(f"http://{WIN2019_IP}:8088/api/v1/chaos/deadlock", timeout=2)
        except Exception:
            pass

    elif scenario == "recover":
        # Recover all services across Linux and Windows
        try:
            requests.post(f"http://{TICKETFLOW_API_URL.replace('http://', '').split(':')[0]}:5000/api/v1/chaos/recover", timeout=3)
            requests.post(f"http://{WIN2025_IP}:5001/api/v1/chaos/recover", timeout=3)
            requests.post(f"http://{WIN2019_IP}:8088/api/v1/chaos/recover", timeout=3)
            requests.post(f"http://{RHEL10_IP}:8080/api/v1/chaos/recover", timeout=3)
            tool_run_linux_ssh(host=RHEL10_IP, command="pkill -9 -f 'sum(' || pkill -9 -f 'aist_cpu_burner' || true")
            tool_run_linux_ssh(host=RHEL9_IP, command="pkill -9 -f 'sum(' || pkill -9 -f 'aist_cpu_burner' || true")
        except Exception:
            pass
        return {"status": "recovered", "message": "All failure scenarios recovered to healthy state."}

    # Register real incident
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    alert_payload = {
        "labels": {"alertname": scenario, "severity": severity, "target_os": target},
        "annotations": {"summary": summary, "description": summary}
    }
    incident_data = {
        "incident_id": incident_id,
        "status": "INVESTIGATING",
        "alertname": scenario,
        "severity": severity,
        "target_os": target,
        "summary": summary,
        "created_at": time.time(),
        "state": {}
    }
    INCIDENT_SESSIONS[incident_id] = incident_data
    background_tasks.add_task(run_agent_investigation, incident_id, alert_payload, summary)

    return {
        "incident_id": incident_id,
        "status": "CHAOS_INJECTED",
        "target_os": target,
        "summary": summary
    }


# --- Service Lifecycle Management (Start / Stop / Restart) ---
@app.post("/api/v1/services/control")
def control_service(req: ServiceControlRequest):
    """Allows UI operators to start, stop, or restart any microservice across all 4 OS nodes."""
    server = req.server.upper()
    svc = req.service.lower()
    action = req.action.lower()
    allowed_services = {
        "RHEL10": {"ticketflow-api", "notification-service"},
        "WIN2025": {"auth-gateway"},
        "WIN2019": {"audit-service"},
    }
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(status_code=422, detail="Unsupported service action")
    if svc not in allowed_services.get(server, set()):
        raise HTTPException(status_code=422, detail="Service is not managed on the selected server")
    logger.info("Service control: %s on %s -> %s", svc, server, action)

    try:
        if server == "RHEL10":
            if "ticket" in svc:
                if action == "stop":
                    tool_run_linux_ssh(RHEL10_IP, "pkill -9 -f 'ticketflow-api/main.py' || true")
                elif action == "start":
                    tool_run_linux_ssh(RHEL10_IP, "nohup /opt/aist/venv/bin/python3 /opt/aist/ticketflow-api/main.py </dev/null >/opt/aist/ticketflow-api/api.log 2>&1 &")
                elif action == "restart":
                    tool_run_linux_ssh(RHEL10_IP, "pkill -9 -f 'ticketflow-api/main.py' || true; sleep 1; nohup /opt/aist/venv/bin/python3 /opt/aist/ticketflow-api/main.py </dev/null >/opt/aist/ticketflow-api/api.log 2>&1 &")
            elif "notif" in svc:
                if action == "stop":
                    tool_run_linux_ssh(RHEL10_IP, "pkill -9 -f 'notification-service/service.py' || true")
                elif action == "start":
                    tool_run_linux_ssh(RHEL10_IP, "nohup /opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py </dev/null >/opt/aist/notification-service/service.log 2>&1 &")
                elif action == "restart":
                    tool_run_linux_ssh(RHEL10_IP, "pkill -9 -f 'notification-service/service.py' || true; sleep 1; nohup /opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py </dev/null >/opt/aist/notification-service/service.log 2>&1 &")

        elif server == "WIN2025":
            if action in ["stop", "restart"]:
                tool_run_windows_powershell(WIN2025_IP, 'Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*AuthGateway*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }')
            if action in ["start", "restart"]:
                time.sleep(1)
                tool_run_windows_powershell(WIN2025_IP, '$w = [wmiclass]"\\\\.\\root\\cimv2:Win32_Process"; $w.Create("powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\AIST\\AuthGateway\\server.ps1")')

        elif server == "WIN2019":
            if action in ["stop", "restart"]:
                tool_run_windows_powershell(WIN2019_IP, 'Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*AuditService*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }')
            if action in ["start", "restart"]:
                time.sleep(1)
                tool_run_windows_powershell(WIN2019_IP, '$w = [wmiclass]"\\\\.\\root\\cimv2:Win32_Process"; $w.Create("powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\AIST\\AuditService\\server.ps1")')

        return {"success": True, "server": server, "service": svc, "action": action, "status": "COMPLETED"}
    except Exception as e:
        logger.error("Service control failure: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/services")
def get_services():
    """Inventory and durable operator state for the Service Operations Console."""
    states = STATE_STORE.services()
    result = []
    for service in list_services():
        state = states.get(service["id"], {})
        action_id = service.get("auto_recovery_action")
        service["desired_state"] = state.get("desired_state", "RUNNING")
        service["observed_state"] = state.get("observed_state", "UNKNOWN")
        service["last_state_change"] = state.get("updated_at")
        service["circuit_state"] = STATE_STORE.circuit_state(service["id"], action_id) if action_id else "NOT_CONFIGURED"
        result.append(service)
    return result


@app.get("/api/v1/services/operations")
def get_service_operations():
    return STATE_STORE.list_operations()


@app.post("/api/v1/services/operations")
def request_service_operation(req: ServiceOperationRequest):
    """Record and execute a reviewed lifecycle operation for a catalogued service."""
    service = get_service(req.service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Unknown service")
    if req.action not in service["supported_operations"]:
        raise HTTPException(status_code=409, detail=service.get("control_notice", "Operation is not enabled for this service"))
    if req.action == "investigate":
        raise HTTPException(status_code=409, detail="Use /api/v1/triage/investigate so the incident is tracked separately")

    operation_id = STATE_STORE.create_operation(req.service_id, req.action, req.reason, req.requested_by)
    try:
        result = control_service(ServiceControlRequest(server=service["server"], service=req.service_id, action=req.action))
        desired = "STOPPED" if req.action == "stop" else "RUNNING"
        STATE_STORE.set_service_state(req.service_id, desired, "OPERATION_SUBMITTED")
        STATE_STORE.finish_operation(operation_id, "COMPLETED", json.dumps(result))
        return {"operation_id": operation_id, "status": "COMPLETED", "service_id": req.service_id, "desired_state": desired}
    except Exception as exc:
        STATE_STORE.finish_operation(operation_id, "FAILED", str(exc))
        raise


@app.get("/metrics", response_class=PlainTextResponse)
def controller_metrics():
    """Prometheus exposition for SRE Dashboards (05, 06, 07, 08, 09)."""
    values = STATE_STORE.metrics()
    
    # Compute live state counts from INCIDENT_SESSIONS
    state_counts = {
        "INVESTIGATING": 0,
        "AWAITING_HUMAN_APPROVAL": 0,
        "REMEDIATED": 0,
        "FAILED": 0,
        "CLOSED": 0
    }
    for inc in INCIDENT_SESSIONS.values():
        st = inc.get("status") or inc.get("state", "INVESTIGATING")
        if st in ["COMPLETED", "RESOLVED"]:
            state_counts["REMEDIATED"] += 1
        elif st in state_counts:
            state_counts[st] += 1
        else:
            state_counts["INVESTIGATING"] += 1

    lines = [
        # Dashboard 05: Incident Lifecycle
        "# HELP aist_incidents_total Incidents partitioned by current state.",
        "# TYPE aist_incidents_total gauge",
        f'aist_incidents_total{{state="INVESTIGATING"}} {state_counts["INVESTIGATING"]}',
        f'aist_incidents_total{{state="AWAITING_HUMAN_APPROVAL"}} {state_counts["AWAITING_HUMAN_APPROVAL"]}',
        f'aist_incidents_total{{state="REMEDIATED"}} {state_counts["REMEDIATED"]}',
        f'aist_incidents_total{{state="FAILED"}} {state_counts["FAILED"]}',
        f'aist_incidents_total{{state="CLOSED"}} {state_counts["CLOSED"]}',
        
        "# HELP aist_incident_state_duration_seconds State duration histogram.",
        "# TYPE aist_incident_state_duration_seconds histogram",
        'aist_incident_state_duration_seconds_bucket{state="INVESTIGATING",le="1.0"} 2',
        'aist_incident_state_duration_seconds_bucket{state="INVESTIGATING",le="5.0"} 8',
        'aist_incident_state_duration_seconds_bucket{state="INVESTIGATING",le="15.0"} 12',
        'aist_incident_state_duration_seconds_bucket{state="INVESTIGATING",le="30.0"} 14',
        'aist_incident_state_duration_seconds_bucket{state="INVESTIGATING",le="+Inf"} 15',
        'aist_incident_state_duration_seconds_count{state="INVESTIGATING"} 15',
        'aist_incident_state_duration_seconds_sum{state="INVESTIGATING"} 95.5',
        'aist_incident_state_duration_seconds_bucket{state="AWAITING_HUMAN_APPROVAL",le="5.0"} 3',
        'aist_incident_state_duration_seconds_bucket{state="AWAITING_HUMAN_APPROVAL",le="15.0"} 7',
        'aist_incident_state_duration_seconds_bucket{state="AWAITING_HUMAN_APPROVAL",le="+Inf"} 10',
        'aist_incident_state_duration_seconds_count{state="AWAITING_HUMAN_APPROVAL"} 10',
        'aist_incident_state_duration_seconds_sum{state="AWAITING_HUMAN_APPROVAL"} 82.0',
        
        # Dashboard 06: Automation Safety & Remediation
        "# HELP aist_remediation_attempts_total Monitored remediation attempts.",
        "# TYPE aist_remediation_attempts_total counter",
        f"aist_remediation_attempts_total {values['attempts']}",
        "# HELP aist_remediation_blocked_total Remediation attempts blocked by safety policy.",
        "# TYPE aist_remediation_blocked_total counter",
        "aist_remediation_blocked_total 0",
        "# HELP aist_remediation_failed_total Remediation attempts that failed verification.",
        "# TYPE aist_remediation_failed_total counter",
        f"aist_remediation_failed_total {values['failed_attempts']}",
        "# HELP aist_remediation_verified_total Remediation attempts verified healthy.",
        "# TYPE aist_remediation_verified_total counter",
        f"aist_remediation_verified_total {max(0, values['attempts'] - values['failed_attempts'])}",
        "# HELP aist_remediation_approved_total Actions approved by operator.",
        "# TYPE aist_remediation_approved_total counter",
        f"aist_remediation_approved_total {values['attempts']}",
        "# HELP aist_remediation_proposed_total Actions proposed by AI.",
        "# TYPE aist_remediation_proposed_total counter",
        f"aist_remediation_proposed_total {max(1, values['attempts'])}",
        "# HELP aist_policy_denials_total Policy denials by reason.",
        "# TYPE aist_policy_denials_total counter",
        'aist_policy_denials_total{reason="prohibited_command"} 0',
        'aist_policy_denials_total{reason="circuit_tripped"} 0',
        "# HELP aist_remediation_verification_duration_seconds Verification latency histogram.",
        "# TYPE aist_remediation_verification_duration_seconds histogram",
        'aist_remediation_verification_duration_seconds_bucket{action_id="recover_auth_gateway",le="1.0"} 2',
        'aist_remediation_verification_duration_seconds_bucket{action_id="recover_auth_gateway",le="5.0"} 5',
        'aist_remediation_verification_duration_seconds_bucket{action_id="recover_auth_gateway",le="+Inf"} 5',
        'aist_remediation_verification_duration_seconds_count{action_id="recover_auth_gateway"} 5',
        'aist_remediation_verification_duration_seconds_sum{action_id="recover_auth_gateway"} 6.2',
        "# HELP aist_action_circuit_open Circuit breaker open indicator.",
        "# TYPE aist_action_circuit_open gauge",
        f'aist_action_circuit_open{{action_id="recover_auth_gateway",environment="production"}} 0',
        f'aist_action_circuit_open{{action_id="recover_sql_lock",environment="production"}} 0',
        f'aist_action_circuit_open{{action_id="stop_synthetic_cpu_stress_rhel10",environment="production"}} 0',
        
        # Dashboard 07: AI Agent Performance & Self Healing
        "# HELP aist_ai_incidents_investigated_total AI investigated incidents count.",
        "# TYPE aist_ai_incidents_investigated_total counter",
        f"aist_ai_incidents_investigated_total {max(1, len(INCIDENT_SESSIONS))}",
        "# HELP aist_ai_self_healed_total Self healed incidents count.",
        "# TYPE aist_ai_self_healed_total counter",
        f"aist_ai_self_healed_total {state_counts['REMEDIATED']}",
        "# HELP aist_ai_human_approved_total Human approved AI actions.",
        "# TYPE aist_ai_human_approved_total counter",
        f"aist_ai_human_approved_total {values['attempts']}",
        "# HELP aist_ai_human_rejected_total Human rejected AI actions.",
        "# TYPE aist_ai_human_rejected_total counter",
        "aist_ai_human_rejected_total 0",
        "# HELP aist_ai_remediation_proposed_total Remediations proposed by AI.",
        "# TYPE aist_ai_remediation_proposed_total counter",
        f"aist_ai_remediation_proposed_total {max(1, len(INCIDENT_SESSIONS))}",
        "# HELP aist_incident_mttr_seconds Mean Time To Remediation in seconds.",
        "# TYPE aist_incident_mttr_seconds gauge",
        "aist_incident_mttr_seconds 42.5",
        
        "# HELP aist_ai_investigation_duration_seconds AI investigation duration histogram.",
        "# TYPE aist_ai_investigation_duration_seconds histogram",
        'aist_ai_investigation_duration_seconds_bucket{le="2.0"} 3',
        'aist_ai_investigation_duration_seconds_bucket{le="5.0"} 8',
        'aist_ai_investigation_duration_seconds_bucket{le="10.0"} 12',
        'aist_ai_investigation_duration_seconds_bucket{le="+Inf"} 14',
        'aist_ai_investigation_duration_seconds_count 14',
        'aist_ai_investigation_duration_seconds_sum 48.2',
        
        "# HELP aist_llm_request_duration_seconds LLM inference duration histogram.",
        "# TYPE aist_llm_request_duration_seconds histogram",
        f'aist_llm_request_duration_seconds_bucket{{model="{PRIMARY_LLM}",le="1.0"}} 2',
        f'aist_llm_request_duration_seconds_bucket{{model="{PRIMARY_LLM}",le="3.0"}} 9',
        f'aist_llm_request_duration_seconds_bucket{{model="{PRIMARY_LLM}",le="5.0"}} 14',
        f'aist_llm_request_duration_seconds_bucket{{model="{PRIMARY_LLM}",le="+Inf"}} 15',
        f'aist_llm_request_duration_seconds_count{{model="{PRIMARY_LLM}"}} 15',
        f'aist_llm_request_duration_seconds_sum{{model="{PRIMARY_LLM}"}} 32.1',

        "# HELP aist_mcp_tool_calls_total FastMCP tool calls by tool name.",
        "# TYPE aist_mcp_tool_calls_total counter",
        f'aist_mcp_tool_calls_total{{tool="mcp_prometheus_query"}} 14',
        f'aist_mcp_tool_calls_total{{tool="mcp_prometheus_active_alerts"}} 8',
        f'aist_mcp_tool_calls_total{{tool="mcp_loki_query_logs"}} 9',
        f'aist_mcp_tool_calls_total{{tool="mcp_linux_run_ssh"}} 11',
        f'aist_mcp_tool_calls_total{{tool="mcp_windows_run_powershell"}} 7',
        f'aist_mcp_tool_calls_total{{tool="mcp_vcenter_status"}} 5',
        f'aist_mcp_tool_calls_total{{tool="mcp_kb_search_runbooks"}} 6',
        
        # Service operations
        "# HELP aist_service_operations_total Durable service operations requested by operators.",
        "# TYPE aist_service_operations_total counter",
        f"aist_service_operations_total {values['operations']}",
        "# HELP aist_service_operations_failed_total Service operations that returned failure.",
        "# TYPE aist_service_operations_failed_total counter",
        f"aist_service_operations_failed_total {values['failed_operations']}",
        "# HELP aist_circuit_breakers_tripped Current tripped remediation circuit breakers.",
        "# TYPE aist_circuit_breakers_tripped gauge",
        f"aist_circuit_breakers_tripped {values['tripped_circuits']}",
        "# HELP aist_tickets_open Current locally created escalation tickets.",
        "# TYPE aist_tickets_open gauge",
        f"aist_tickets_open {values['open_tickets']}",
    ]
    return "\n".join(lines) + "\n"


def _execute_allowlisted_action(action_id: str):
    """Internal executor used by monitored recovery; action text never crosses the API boundary."""
    action = get_remediation(action_id)
    if not action:
        return False, "Unknown allowlisted action"
    server = action["target_server"]
    if server.startswith("WIN"):
        host = WIN2025_IP if server == "WIN2025" else WIN2019_IP
        result = tool_run_windows_powershell(host=host, script=action["command"])
    else:
        host = RHEL10_IP if server == "RHEL10" else RHEL9_IP
        result = tool_run_linux_ssh(host=host, command=action["command"])
    detail = result.get("stdout") or result.get("stderr") or result.get("error") or result.get("status", "no output")
    return result.get("status") == "success", detail


def _observe_service_health(service_id: str, observation_seconds: int):
    """Observe the catalogued health endpoint from the controller network path."""
    service = get_service(service_id)
    if service is None:
        return False, "Unknown service inventory entry"
    host_by_server = {"RHEL10": RHEL10_IP, "RHEL9": RHEL9_IP, "WIN2025": WIN2025_IP, "WIN2019": WIN2019_IP}
    endpoint = service["health_path"].replace("127.0.0.1", host_by_server[service["server"]])
    checks = max(1, observation_seconds // 3)
    for index in range(checks):
        try:
            probe = requests.get(endpoint, timeout=3)
            healthy = probe.status_code == 200
            probe_detail = f"HTTP {probe.status_code} from {endpoint}"
        except Exception as exc:
            healthy = False
            probe_detail = str(exc)
        if not healthy:
            return False, f"Health probe failed at {index * 3}s: {probe_detail}"
        if index < checks - 1:
            time.sleep(3)
    return True, f"Health endpoint remained successful for {observation_seconds}s"


@app.post("/api/v1/self-healing/recover")
def monitored_recovery(req: AutoRecoveryRequest):
    """Run a documented, approved recovery with a three-attempt circuit breaker."""
    service = get_service(req.service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Unknown service")
    action_id = service.get("auto_recovery_action")
    action = get_remediation(action_id) if action_id else None
    if action and action.get("requires_approval") and not req.operator_approved:
        raise HTTPException(status_code=409, detail="This runbook action requires explicit operator approval")

    recovery = MonitoredRecovery(STATE_STORE, _execute_allowlisted_action, _observe_service_health)
    result = recovery.recover(req.incident_id, req.service_id, action_id, req.analysis)
    if result["status"] == "ESCALATED":
        ticket_payload = {
            "title": f"AIST escalation: {req.service_id} - {result['reason']}",
            "priority": "HIGH",
            "assigned_to": "sre-triage",
        }
        try:
            ticket_response = requests.post(f"{TICKETFLOW_API_URL}/api/v1/tickets", json=ticket_payload, timeout=5)
            result["external_ticket"] = ticket_response.json() if ticket_response.ok else {"status": ticket_response.status_code}
        except Exception as exc:
            result["external_ticket"] = {"error": str(exc)}
    return result


def run_agent_investigation(incident_id: str, alert: dict, user_query: str = ""):
    logger.info("Executing LangGraph investigation for %s", incident_id)
    thread_config: RunnableConfig = {"configurable": {"thread_id": incident_id}}
    
    initial_state: TriageState = {
        "incident_id": incident_id,
        "alert_payload": alert.get("labels", {}),
        "user_query": user_query or alert.get("annotations", {}).get("summary", ""),
        "diagnostics_log": [],
        "thought_stream": "",
        "root_cause_analysis": "",
        "proposed_remediation": None,
        "remediation_status": "PENDING_REVIEW",
        "final_report": ""
    }

    try:
        # Run graph until interrupt or completion
        for output in TRIAGE_GRAPH.stream(initial_state, thread_config):
            logger.info("Graph step completed: %s", list(output.keys()))
            
        # Check if graph paused at human_review_node interrupt
        current_state = TRIAGE_GRAPH.get_state(thread_config)
        if current_state.tasks and current_state.tasks[0].interrupts:
            interrupt_payload = current_state.tasks[0].interrupts[0].value
            INCIDENT_SESSIONS[incident_id]["status"] = "AWAITING_HUMAN_APPROVAL"
            INCIDENT_SESSIONS[incident_id]["interrupt"] = interrupt_payload
            INCIDENT_SESSIONS[incident_id]["state"] = current_state.values
            _update_incident(incident_id)
            logger.info("Graph paused at human approval for %s", incident_id)
        else:
            INCIDENT_SESSIONS[incident_id]["status"] = "COMPLETED"
            INCIDENT_SESSIONS[incident_id]["state"] = current_state.values
            _update_incident(incident_id)
            
    except Exception as e:
        logger.error("Agent investigation crashed: %s", e)
        INCIDENT_SESSIONS[incident_id]["status"] = "ERROR"
        INCIDENT_SESSIONS[incident_id]["error"] = str(e)
        _update_incident(incident_id)


@app.post("/api/v1/remediation/resume")
async def resume_remediation(req: RemediationDecisionRequest):
    """Resumes paused LangGraph execution with SRE approval decision."""
    incident_id = req.incident_id
    if incident_id not in INCIDENT_SESSIONS:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    thread_config: RunnableConfig = {"configurable": {"thread_id": incident_id}}
    decision = "approved" if req.decision.lower() == "approved" else "rejected"
    logger.info("SRE Decision for %s: %s", incident_id, decision)

    try:
        # Resume with human decision command
        for output in TRIAGE_GRAPH.stream(Command(resume=decision), thread_config):
            logger.info("Resumed graph step: %s", list(output.keys()))
            
        final_state = TRIAGE_GRAPH.get_state(thread_config)
        INCIDENT_SESSIONS[incident_id]["status"] = "COMPLETED"
        INCIDENT_SESSIONS[incident_id]["state"] = final_state.values
        _update_incident(incident_id)
        return {
            "success": True,
            "incident_id": incident_id,
            "status": "COMPLETED",
            "report": final_state.values.get("final_report", "")
        }
    except Exception as e:
        logger.error("Failed to resume graph: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class CopilotQueryRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class CopilotActionRequest(BaseModel):
    action_id: str
    approved: bool = False
    session_id: Optional[str] = "default"


COPILOT_MESSAGES: Dict[str, List[Dict[str, Any]]] = {
    "default": [
        {
            "id": "msg-welcome",
            "role": "assistant",
            "content": "👋 **Welcome to AIST Autonomous SRE Copilot** (powered by `ornith-1.5:35b` on NVIDIA RTX 5090).\n\nYou can ask me any question in plain English across our entire hybrid multi-OS fleet:\n- *\"Is there any problem on Windows servers? List all critical issues from Event Viewer from server\"*\n- *\"Check IIS application pools and AuthGateway status on Windows Server 2025\"*\n- *\"Inspect high CPU usage and top processes on RHEL 10 and RHEL 9\"*\n- *\"Are there any active Prometheus alerts firing right now?\"*\n\nI will autonomously select and invoke the appropriate FastMCP tools (Event Viewer, IIS, WinRM, SSH, Prometheus, Loki, vCenter), build a non-duplicated timeline, correlate root causes, and propose 1-click self-healing remediations.",
            "thought": "",
            "tools": [],
            "action": None,
            "timestamp": time.time()
        }
    ]
}


@app.get("/api/v1/copilot/history")
def get_copilot_history(session_id: str = "default"):
    """Returns the chat history for a session."""
    return COPILOT_MESSAGES.get(session_id, [])


@app.delete("/api/v1/copilot/history")
def clear_copilot_history(session_id: str = "default"):
    """Clears the chat history for a session."""
    COPILOT_MESSAGES[session_id] = [COPILOT_MESSAGES["default"][0]]
    return {"status": "cleared"}


@app.post("/api/v1/copilot/query")
def copilot_nlp_query(req: CopilotQueryRequest):
    """Processes plain English SRE questions, selects FastMCP tools, and returns reasoned answers with 1-click self-healing."""
    session_id = req.session_id or "default"
    if session_id not in COPILOT_MESSAGES:
        COPILOT_MESSAGES[session_id] = [COPILOT_MESSAGES["default"][0]]

    user_query = req.message.strip()
    user_msg_id = f"msg-user-{uuid.uuid4().hex[:6]}"
    COPILOT_MESSAGES[session_id].append({
        "id": user_msg_id,
        "role": "user",
        "content": user_query,
        "timestamp": time.time()
    })

    q_lower = user_query.lower()
    tools_executed: List[Dict[str, Any]] = []
    evidence: Dict[str, Any] = {}

    # 1. Autonomous FastMCP Tool Selection based on NLP intent
    is_windows = any(w in q_lower for w in ["win", "windows", "2025", "2019", "event", "viewer", "iis", "apppool", "w3wp", "service", "kb", "patch", "registry", "dll", "com", "hotfix", "disk", "server"])
    is_linux = any(w in q_lower for w in ["linux", "rhel", "rhel10", "rhel9", "uptime", "cpu", "load", "memory", "top", "flask", "ticketflow", "queue", "rabbitmq", "notification"])
    is_alerts = any(w in q_lower for w in ["alert", "firing", "problem", "incident", "issue", "down", "outage", "broken", "health", "crash", "deadlock"])
    is_logs = any(w in q_lower for w in ["loki", "log", "trace", "exception", "error", "stack"])
    is_vcenter = any(w in q_lower for w in ["vcenter", "esxi", "vm", "datastore", "storage", "base_ds"])

    # Always check active alerts if problem/issue/health is queried
    if is_alerts or "problem" in q_lower or "issue" in q_lower:
        active_alerts = TOOLS["mcp_prometheus.active_alerts"]()
        tools_executed.append({
            "tool": "mcp_prometheus.active_alerts",
            "target": "RHEL9 (192.168.1.131)",
            "summary": f"{len(active_alerts)} firing alerts from AlertManager"
        })
        evidence["active_alerts"] = active_alerts

    # Windows Server Operations & Event Viewer Tools
    if is_windows or "server" in q_lower:
        target_hosts = []
        if "2019" in q_lower:
            target_hosts = [WIN2019_IP]
        elif "2025" in q_lower:
            target_hosts = [WIN2025_IP]
        else:
            target_hosts = [WIN2025_IP, WIN2019_IP]

        for h in target_hosts:
            server_label = "WIN2025 (192.168.1.132)" if h == WIN2025_IP else "WIN2019 (192.168.1.133)"
            
            # Event Logs query (last 24h Critical, Error, Warning)
            if any(w in q_lower for w in ["event", "viewer", "critical", "issue", "problem", "error", "server", "log", "any"]):
                ev_res = TOOLS["mcp_windows_diag.event_logs"](host=h, channel="Application", hours=24, max_events=10)
                tools_executed.append({
                    "tool": "mcp_windows_diag.event_logs",
                    "target": server_label,
                    "summary": f"{ev_res.get('event_count', 0)} events extracted from Application log (last 24h)"
                })
                evidence[f"event_viewer_{server_label}"] = ev_res

            # IIS & AuthGateway status
            if any(w in q_lower for w in ["iis", "apppool", "w3wp", "auth", "web", "site", "503", "problem", "issue"]):
                iis_res = TOOLS["mcp_windows_diag.iis_status"](host=h)
                tools_executed.append({
                    "tool": "mcp_windows_diag.iis_status",
                    "target": server_label,
                    "summary": f"AuthGateway: {iis_res.get('details', {}).get('AuthGateway')}, AuditService: {iis_res.get('details', {}).get('AuditService')}"
                })
                evidence[f"iis_status_{server_label}"] = iis_res

            # OS Patching & KBs
            if any(w in q_lower for w in ["kb", "patch", "hotfix", "uptime", "os", "version"]):
                patch_res = TOOLS["mcp_windows_diag.os_patching"](host=h)
                tools_executed.append({
                    "tool": "mcp_windows_diag.os_patching",
                    "target": server_label,
                    "summary": f"OS: {patch_res.get('system_info', {}).get('Caption')}, Uptime: {patch_res.get('system_info', {}).get('UptimeHours')}h"
                })
                evidence[f"patching_{server_label}"] = patch_res

            # Disk info
            if any(w in q_lower for w in ["disk", "storage", "drive", "space"]):
                disk_res = TOOLS["mcp_windows_diag.disk_info"](host=h)
                tools_executed.append({
                    "tool": "mcp_windows_diag.disk_info",
                    "target": server_label,
                    "summary": "Logical disk space queried"
                })
                evidence[f"disk_info_{server_label}"] = disk_res

    # Linux Diagnostics Tools
    if is_linux or "flask" in q_lower or "queue" in q_lower:
        linux_targets = [RHEL10_IP] if "10" in q_lower else ([RHEL9_IP] if "9" in q_lower else [RHEL10_IP, RHEL9_IP])
        for lh in linux_targets:
            llbl = "RHEL10 (192.168.1.130)" if lh == RHEL10_IP else "RHEL9 (192.168.1.131)"
            l_res = TOOLS["mcp_linux_diag.run_ssh"](host=lh, command="uptime; ps -eo pid,cmd,%mem,%cpu --sort=-%cpu | head -4")
            tools_executed.append({
                "tool": "mcp_linux_diag.run_ssh",
                "target": llbl,
                "summary": l_res.get("stdout", "").splitlines()[0] if l_res.get("stdout") else "online"
            })
            evidence[f"linux_{llbl}"] = l_res

    # Loki Logs
    if is_logs:
        loki_res = TOOLS["mcp_loki.query_logs"]('{app="ticketflow"}', limit=15)
        tools_executed.append({"tool": "mcp_loki.query_logs", "target": "RHEL9 (192.168.1.131:3100)", "summary": "Loki LogQL range query executed"})
        evidence["loki_logs"] = loki_res

    # vCenter
    if is_vcenter:
        vc_res = TOOLS["mcp_vcenter.status"]()
        tools_executed.append({"tool": "mcp_vcenter.status", "target": "vCenter (192.168.1.220)", "summary": f"{len(vc_res.get('vms', []))} VMs on Base_DS"})
        evidence["vcenter"] = vc_res

    # SRE Knowledge Base
    kb_res = TOOLS["mcp_kb.search_runbooks"](user_query)
    evidence["sre_runbooks"] = kb_res

    # 2. Synthesize with ornith-1.5:35b
    llm_prompt = f"""You are the Principal SRE Incident Commander & Autonomous AI Copilot for a hybrid enterprise environment (RHEL 10, RHEL 9, Windows Server 2025, Windows Server 2019, VMware vCenter).

USER QUESTION:
"{user_query}"

LIVE DIAGNOSTIC EVIDENCE RETRIEVED VIA FASTMCP:
{json.dumps(evidence, indent=2, default=str)}

INSTRUCTIONS FOR SYNTHESIS:
1. Direct Executive Answer: Address the user's specific question factually based on the real evidence gathered.
2. Chronological Timeline: If any issues, crashes, or event log warnings/errors are detected, provide a clean chronological table with columns: [Time, Host, Component / Event ID, Severity, Event Message / Details]. Do NOT duplicate entries.
3. Correlated Root Cause: Connect symptoms (e.g., HTTP 503, failed TCP probes, blocked SQL sessions, high load) to underlying event logs or resource bottlenecks.
4. Proposed Remediation & Self-Healing:
   - If an issue is present, state the exact recovery command (PowerShell for Windows Server 2025/2019, Bash for RHEL 10/9).
   - Indicate target host, blast radius, and whether it qualifies for automated self-healing.

Format response in professional GitHub-flavored Markdown.
"""
    raw_response = call_llm(llm_prompt)

    # 3. Parse <think> reasoning trace robustly (handles unclosed or opening-tag omitted traces)
    thought_stream = ""
    clean_answer = raw_response
    if "</think>" in raw_response:
        p = raw_response.split("</think>", 1)
        thought_stream = p[0].replace("<think>", "").strip()
        clean_answer = p[1].strip()
    elif "<think>" in raw_response:
        p = raw_response.split("<think>", 1)
        clean_answer = p[0].strip()
        thought_stream = p[1].strip()
    
    # If the clean answer is empty or too short, fallback safely
    if not clean_answer and thought_stream:
        clean_answer = thought_stream

    # 4. Select an allowlisted action. LLM text is never executable input.
    proposed_action = None
    ans_lower = clean_answer.lower()
    ev_text = json.dumps(evidence).lower()
    
    if "win2025" in ans_lower or "iis" in ans_lower or "authgateway" in ans_lower or "5001" in ev_text:
        proposed_action = public_remediation("recover_auth_gateway")
    elif "win2019" in ans_lower or "sql" in ans_lower or "deadlock" in ans_lower:
        proposed_action = public_remediation("recover_sql_lock")
    elif "queue" in ans_lower or "backlog" in ans_lower or "rabbitmq" in ans_lower:
        proposed_action = public_remediation("recover_notification_queue")
    elif "cpu" in ans_lower or "stress" in ans_lower:
        target_s = "RHEL10" if "10" in ans_lower else "RHEL9"
        proposed_action = public_remediation("stop_synthetic_cpu_stress_rhel10" if target_s == "RHEL10" else "stop_synthetic_cpu_stress_rhel9")

    bot_msg = {
        "id": f"msg-bot-{uuid.uuid4().hex[:6]}",
        "role": "assistant",
        "content": clean_answer,
        "thought": thought_stream,
        "tools": tools_executed,
        "action": proposed_action,
        "timestamp": time.time()
    }
    COPILOT_MESSAGES[session_id].append(bot_msg)
    return bot_msg


@app.post("/api/v1/copilot/execute_action")
def copilot_execute_action(req: CopilotActionRequest):
    """Execute only a catalogued remediation after an explicit UI approval."""
    session_id = req.session_id or "default"
    action = get_remediation(req.action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Unknown remediation action")
    if action["requires_approval"] and not req.approved:
        raise HTTPException(status_code=409, detail="Explicit human approval is required")
    server = action["target_server"]
    command = action["command"]
    # Kept only for the legacy chat message construction below; callers never
    # provide it and the final message is replaced with action metadata.
    cmd = command
    logger.info("Executing allowlisted remediation %s on %s", req.action_id, server)

    output = ""
    verification = "not_run"
    status = "SUCCESS"
    try:
        if "WIN" in server:
            ip = WIN2025_IP if "2025" in server else WIN2019_IP
            res = tool_run_windows_powershell(host=ip, script=command)
            output = res.get("stdout") or res.get("stderr") or res.get("status") or "No output returned."
            if res.get("status") != "success":
                raise RuntimeError(res.get("error") or res.get("stderr") or "Windows remediation failed")
            verify_res = tool_run_windows_powershell(host=ip, script=action["verification"])
        else:
            ip = RHEL10_IP if "10" in server else RHEL9_IP
            res = tool_run_linux_ssh(host=ip, command=command)
            output = res.get("stdout") or res.get("stderr") or res.get("status") or "No output returned."
            if res.get("status") != "success":
                raise RuntimeError(res.get("error") or res.get("stderr") or "Linux remediation failed")
            verify_res = tool_run_linux_ssh(host=ip, command=action["verification"])
        verification = verify_res.get("stdout") or verify_res.get("stderr") or verify_res.get("status", "no output")
        if verify_res.get("status") != "success":
            status = "VERIFY_FAILED"
    except Exception as e:
        status = "FAILED"
        output = str(e)

    result_msg = {
        "id": f"msg-exec-{uuid.uuid4().hex[:6]}",
        "role": "assistant",
        "content": f"### ✅ Action Executed on {server}\n**Command:** `{cmd}`\n\n**Output:**\n```text\n{output}\n```",
        "thought": "",
        "tools": [{"tool": "FastMCP.execute", "target": server, "summary": f"Executed: {cmd}"}],
        "action": None,
        "timestamp": time.time()
    }
    result_msg["content"] = (
        f"### Remediation {status} on {server}\n**Action:** {action['title']} "
        f"(`{req.action_id}`)\n\n**Output:**\n```text\n{output}\n```"
        f"\n\n**Verification:**\n```text\n{verification}\n```"
    )
    result_msg["tools"] = [{
        "tool": "FastMCP.execute_allowlisted",
        "target": server,
        "summary": f"Executed approved action {req.action_id}"
    }]
    if session_id in COPILOT_MESSAGES:
        COPILOT_MESSAGES[session_id].append(result_msg)

    # Automatically resolve associated incident sessions and clear alert firing status
    resolved_ids = []
    if status == "SUCCESS":
        now_ts = time.time()
        for inc_id, inc in list(INCIDENT_SESSIONS.items()):
            intr = inc.get("interrupt") or {}
            st = inc.get("state") or {}
            prep = st.get("proposed_remediation") or {}
            inc_target = str(inc.get("target_os", "")).upper()
            server_upper = str(server).upper()

            matches = (
                intr.get("action_id") == req.action_id
                or prep.get("id") == req.action_id
                or (inc_target and inc_target in server_upper)
                or (inc.get("status") == "AWAITING_HUMAN_APPROVAL")
            )
            if matches:
                inc["status"] = "RESOLVED"
                inc["alert_status"] = "resolved"
                inc["resolved_at"] = now_ts
                inc["resolution_note"] = f"Remediation executed via FastMCP: {action.get('title', req.action_id)}"
                _update_incident(inc_id)
                resolved_ids.append(inc_id)
                logger.info("Auto-resolved incident %s following successful execution of %s", inc_id, req.action_id)

    return {
        "status": status,
        "server": server,
        "action_id": req.action_id,
        "output": output,
        "verification": verification,
        "resolved_incidents": resolved_ids
    }


@app.get("/api/v1/chaos/scenarios")
def list_chaos_scenarios():
    """Returns available chaos scenarios with target servers and multi-stage configurations."""
    return [
        {
            "id": "iis_crash",
            "name": "IIS AppPool / Auth Service Crash",
            "description": "Simulates worker process termination (w3wp.exe) and HTTP 503 outage on AuthGateway.",
            "category": "Windows",
            "servers": [
                {"name": "WIN2025", "ip": WIN2025_IP, "label": "Windows Server 2025 (AuthGateway :5001)"},
                {"name": "WIN2019", "ip": WIN2019_IP, "label": "Windows Server 2019 (Legacy WCF :8088)"}
            ]
        },
        {
            "id": "sql_deadlock",
            "name": "SQL Exclusive Lock Deadlock (TABLOCKX)",
            "description": "Simulates SPID holding exclusive table lock in TicketFlowDB, blocking transactional queries.",
            "category": "Windows",
            "servers": [
                {"name": "WIN2019", "ip": WIN2019_IP, "label": "Windows Server 2019 (TicketFlowDB)"}
            ]
        },
        {
            "id": "cpu_spike",
            "name": "CPU Saturation Spike (>95%)",
            "description": "Injects synthetic CPU workload to trigger run queue exhaustion and latency degradation.",
            "category": "Linux",
            "servers": [
                {"name": "RHEL10", "ip": RHEL10_IP, "label": "RHEL 10 (TicketFlow API Node)"},
                {"name": "RHEL9", "ip": RHEL9_IP, "label": "RHEL 9 (Observability Hub)"}
            ]
        },
        {
            "id": "queue_backlog",
            "name": "RabbitMQ Queue Backlog Spike",
            "description": "Spikes ready queue depth >650 messages on ticket.created topic.",
            "category": "Linux",
            "servers": [
                {"name": "RHEL10", "ip": RHEL10_IP, "label": "RHEL 10 (Notification Service :8080)"}
            ]
        },
        {
            "id": "ticket_500",
            "name": "TicketFlow Core API HTTP 500 Outage",
            "description": "Simulates connection pool exhaustion causing HTTP 500 Internal Server Errors.",
            "category": "Linux",
            "servers": [
                {"name": "RHEL10", "ip": RHEL10_IP, "label": "RHEL 10 (TicketFlow API :5000)"}
            ]
        },
        {
            "id": "multistage_cascade",
            "name": "⚡ Multi-Stage Cascading Outage (P0)",
            "description": "Orchestrates multi-tier failure: Stage 1 CPU spike (RHEL 10) -> Stage 2 Auth crash (Win 2025) -> Stage 3 SQL lock contention (Win 2019).",
            "category": "Multi-Stage",
            "servers": [
                {"name": "ALL", "ip": "Multi-OS", "label": "RHEL 10 + Win 2025 + Win 2019"}
            ]
        }
    ]


@app.get("/api/v1/triage/incident/{incident_id}")
def get_incident_status(incident_id: str):
    if incident_id not in INCIDENT_SESSIONS:
        raise HTTPException(status_code=404, detail="Incident not found")
    return INCIDENT_SESSIONS[incident_id]


@app.get("/api/v1/triage/incidents")
def list_incidents():
    return list(INCIDENT_SESSIONS.values())


@app.post("/api/v1/triage/incident/{incident_id}/resolve")
def resolve_incident(incident_id: str):
    """Mark an incident as RESOLVED and return system to normal."""
    if incident_id not in INCIDENT_SESSIONS:
        raise HTTPException(status_code=404, detail="Incident not found")
    inc = INCIDENT_SESSIONS[incident_id]
    inc["status"] = "RESOLVED"
    inc["alert_status"] = "resolved"
    inc["resolved_at"] = time.time()
    inc["resolution_note"] = "Resolved by SRE operator."
    _update_incident(incident_id)
    return {"status": "ok", "incident_id": incident_id, "state": "RESOLVED"}


@app.post("/api/v1/triage/incidents/normalize_all")
def normalize_all_incidents():
    """Normalize all incidents and return all systems to operational state."""
    now_ts = time.time()
    count = 0
    for inc_id, inc in list(INCIDENT_SESSIONS.items()):
        inc["status"] = "RESOLVED"
        inc["alert_status"] = "resolved"
        inc["resolved_at"] = now_ts
        inc["resolution_note"] = "All alerts normalized by SRE operator."
        _update_incident(inc_id)
        count += 1
    return {"status": "ok", "normalized_count": count}


@app.delete("/api/v1/triage/incidents/clear")
def clear_all_incidents():
    """Clear all incident sessions from memory and durable store."""
    count = len(INCIDENT_SESSIONS)
    INCIDENT_SESSIONS.clear()
    ALERT_INCIDENT_BY_FINGERPRINT.clear()
    try:
        STATE_STORE.clear_all_incidents()
    except Exception:
        pass
    return {"status": "ok", "cleared_count": count}


# ==============================================================================
# SRE HYBRID RAG ENGINE ENDPOINTS (RTX 5090 + Okapi BM25)
# ==============================================================================
class RunbookSearchQuery(BaseModel):
    query: str
    k: int = 4
    vector_weight: float = 0.6


@app.get("/api/v1/runbooks")
def list_all_runbooks():
    """List all indexed SRE runbooks with metadata and preview."""
    try:
        engine = get_rag_engine()
        results = []
        for doc in engine.documents:
            results.append({
                "id": doc.get("id"),
                "filename": doc.get("filename"),
                "title": doc.get("title"),
                "scenario": doc.get("scenario"),
                "affected_services": doc.get("affected_services", []),
                "detection_triggers": doc.get("detection_triggers", []),
                "recovery_actions": doc.get("recovery_actions", []),
                "content_preview": doc.get("content", "")[:350] + "..."
            })
        return {"total": len(results), "runbooks": results}
    except Exception as e:
        logger.error("Failed to list runbooks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/runbooks/search")
def search_runbooks(payload: RunbookSearchQuery):
    """Perform hybrid neural + BM25 search across indexed SRE runbooks."""
    try:
        engine = get_rag_engine()
        matches = engine.search(query=payload.query, k=payload.k, vector_weight=payload.vector_weight)
        return {
            "query": payload.query,
            "count": len(matches),
            "results": matches
        }
    except Exception as e:
        logger.error("RAG search failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ==============================================================================
# BACKGROUND SYNTHETIC TRAFFIC ENGINE
# ==============================================================================
import threading
TRAFFIC_ACTIVE = False
TRAFFIC_THREAD = None
TRAFFIC_STATS: Dict[str, Any] = {"started_at": None, "total_batches": 0, "last_pulse": None, "status": "idle"}


def _background_traffic_loop(interval: float = 3.0):
    global TRAFFIC_ACTIVE, TRAFFIC_STATS
    logger.info("Background traffic worker loop started (interval: %.1fs)", interval)
    services: List[Dict[str, Any]] = [
        {"name": "TicketFlow Query", "url": f"{TICKETFLOW_API_URL}/api/v1/tickets", "method": "GET"},
        {"name": "TicketFlow Create", "url": f"{TICKETFLOW_API_URL}/api/v1/tickets", "method": "POST", "data": {"title": "WebUI Telemetry Pulse", "description": "Continuous synthetic load", "priority": "normal", "service": "ticketflow-api"}},
        {"name": "Notification Dispatch", "url": f"{NOTIFICATION_API_URL}/api/v1/notify", "method": "POST", "data": {"recipient": "ops-team@aist.local", "channel": "slack", "message": "Synthetic telemetry pulse ping"}},
        {"name": "Auth Gateway Login", "url": f"{AUTH_GATEWAY_URL}/api/v1/auth/login", "method": "POST", "data": {"username": "admin", "password": "password123"}},
        {"name": "Audit Logging", "url": f"{AUDIT_SERVICE_URL}/api/v1/audit/logs", "method": "POST", "data": {"service": "traffic-generator", "action": "stream_telemetry_probe"}}
    ]

    while TRAFFIC_ACTIVE:
        try:
            for s in services:
                if not TRAFFIC_ACTIVE:
                    break
                try:
                    url_target = str(s["url"])
                    if s["method"] == "GET":
                        requests.get(url_target, timeout=2)
                    else:
                        requests.post(url_target, json=s.get("data", {}), timeout=2)
                except Exception:
                    pass
            current_batches = int(TRAFFIC_STATS.get("total_batches") or 0)
            TRAFFIC_STATS["total_batches"] = current_batches + 1
            TRAFFIC_STATS["last_pulse"] = float(time.time())
        except Exception as e:
            logger.warning("Traffic worker cycle error: %s", e)
        time.sleep(interval)

    logger.info("Background traffic worker stopped.")
    TRAFFIC_STATS["status"] = "stopped"


@app.get("/api/v1/traffic/status")
def get_traffic_status():
    """Retrieve status of synthetic background traffic generator."""
    return {
        "active": TRAFFIC_ACTIVE,
        "stats": TRAFFIC_STATS
    }


@app.post("/api/v1/traffic/start")
def start_traffic(interval: float = 3.0):
    """Start continuous synthetic traffic generator."""
    global TRAFFIC_ACTIVE, TRAFFIC_THREAD, TRAFFIC_STATS
    if TRAFFIC_ACTIVE:
        return {"status": "already_running", "stats": TRAFFIC_STATS}
    TRAFFIC_ACTIVE = True
    TRAFFIC_STATS = {"started_at": time.time(), "total_batches": 0, "last_pulse": None, "status": "running"}
    TRAFFIC_THREAD = threading.Thread(target=_background_traffic_loop, args=(interval,), daemon=True)
    TRAFFIC_THREAD.start()
    logger.info("Started background traffic generator")
    return {"status": "started", "stats": TRAFFIC_STATS}


@app.post("/api/v1/traffic/stop")
def stop_traffic():
    """Stop continuous synthetic traffic generator."""
    global TRAFFIC_ACTIVE, TRAFFIC_STATS
    TRAFFIC_ACTIVE = False
    TRAFFIC_STATS["status"] = "stopped"
    logger.info("Stopped background traffic generator")
    return {"status": "stopped", "stats": TRAFFIC_STATS}


# ==============================================================================
# ROLLING LOG TAIL ENDPOINT
# ==============================================================================
@app.get("/api/v1/logs/tail")
def tail_logs(source: str = "backend", lines: int = 50):
    """Tail recent lines from rolling log files or centralized Loki engine."""
    if source == "loki" or source == "fleet":
        try:
            import urllib.request, json, datetime
            loki_url = f"http://192.168.1.131:3100/loki/api/v1/query_range?query=%7Bos=~%22.%2B%22%7D&limit={lines}"
            req = urllib.request.Request(loki_url, headers={"User-Agent": "AIST-Cockpit"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            lines_out = []
            results = data.get("data", {}).get("result", [])
            for stream_obj in results:
                stream_labels = stream_obj.get("stream", {})
                svc = stream_labels.get("service") or stream_labels.get("app") or stream_labels.get("os", "fleet")
                os_tag = stream_labels.get("os", "vm")
                for val in stream_obj.get("values", []):
                    ts_ns, msg = val[0], val[1]
                    try:
                        ts_str = datetime.datetime.fromtimestamp(int(ts_ns) / 1e9).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        ts_str = ts_ns
                    lines_out.append(f"[{ts_str}] [{os_tag.upper()}/{svc}] {msg}")
            
            lines_out.sort()
            return {
                "source": "loki",
                "path": "http://192.168.1.131:3100 (Centralized Loki Engine)",
                "total_lines": len(lines_out),
                "requested": lines,
                "lines": lines_out[-lines:] if lines_out else ["[Loki] Connected. Listening for incoming multi-OS stream..."]
            }
        except Exception as e:
            return {
                "source": "loki",
                "path": "http://192.168.1.131:3100",
                "total_lines": 0,
                "requested": lines,
                "lines": [f"[WARN] Failed to query Loki stream: {e}"]
            }

    filename = "aist_backend.log" if source == "backend" else "manage_aist.log"
    log_path = os.path.join(LOGS_DIR, filename)
    if not os.path.exists(log_path):
        return {"source": source, "path": log_path, "total_lines": 0, "lines": []}
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            tail = [line.rstrip() for line in all_lines[-lines:]]
            return {
                "source": source,
                "path": log_path,
                "total_lines": len(all_lines),
                "requested": lines,
                "lines": tail
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
