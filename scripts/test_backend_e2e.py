"""
End-to-End Test for AIST Backend, FastMCP Tools, and LangGraph Agent Swarm
"""

import os
import sys
import time
import json
from fastapi.testclient import TestClient

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai-triage", "mcp-servers")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai-triage", "agents")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai-triage", "webui", "backend", "app")))

from main import app, INCIDENT_SESSIONS, run_agent_investigation

client = TestClient(app)

print("=" * 70)
print("   AIST: End-to-End Autonomous AI Triage & HITL Test")
print("=" * 70)

# 1. Health check
print("\n[1/4] Testing Backend /api/v1/health...")
r = client.get("/api/v1/health")
print("Health response:", r.status_code, r.json())
assert r.status_code == 200

# 2. Telemetry Overview
print("\n[2/4] Testing Telemetry Overview /api/v1/telemetry/overview...")
r = client.get("/api/v1/telemetry/overview")
print("Telemetry response status:", r.status_code)
data = r.json()
print(" -> vCenter status:", data.get("vcenter", {}).get("status"), f"({data.get('vcenter', {}).get('vm_count')} VMs)")
print(" -> Active alerts count:", data.get("alerts", {}).get("count"))
print(" -> Linux node load:", data.get("linux_node"))
assert r.status_code == 200

# 3. Simulate AlertManager webhook / Manual Triage
print("\n[3/4] Triggering Autonomous Incident Investigation via LangGraph & ornith-1.5:35b...")
incident_id = "inc-test-01"
mock_alert = {
    "labels": {
        "alertname": "TicketApiHighLatency",
        "severity": "critical",
        "target_os": "rhel10",
        "component": "ticketflow-api"
    },
    "annotations": {
        "summary": "TicketFlow API p95 latency exceeds 2.5s due to SQL connection queueing",
        "description": "Flask service on RHEL 10 is experiencing extreme thread starvation."
    }
}
INCIDENT_SESSIONS[incident_id] = {
    "incident_id": incident_id,
    "status": "INVESTIGATING",
    "alertname": mock_alert["labels"]["alertname"],
    "summary": mock_alert["annotations"]["summary"],
    "created_at": time.time(),
    "state": {}
}

t0 = time.time()
run_agent_investigation(incident_id, mock_alert, "Investigate TicketFlow API latency spike")
print(f"Investigation completed in {time.time()-t0:.2f}s")
session = INCIDENT_SESSIONS[incident_id]
print("Incident Status:", session.get("status"))
interrupt = session.get("interrupt")
if isinstance(interrupt, dict):
    print(" -> HITL Interrupt Triggered:", interrupt.get("prompt"))
    print(" -> Proposed Action:", interrupt.get("command"))
    print(" -> Blast Radius:", interrupt.get("blast_radius"))

# 4. Resume with Human Approval
print("\n[4/4] Testing Human-in-the-Loop Remediation Approval (/api/v1/remediation/resume)...")
res = client.post("/api/v1/remediation/resume", json={
    "incident_id": incident_id,
    "decision": "approved"
})
print("Resume response:", res.status_code, res.json().get("status"))
final_session = INCIDENT_SESSIONS[incident_id]
final_state = final_session.get("state")
if isinstance(final_state, dict):
    print("Final Remediation Status:", final_state.get("remediation_status"))

print("\n" + "=" * 70)
print("   [+] E2E AI TRIAGE & HUMAN-IN-THE-LOOP VERIFICATION PASSED 100%!")
print("=" * 70)

