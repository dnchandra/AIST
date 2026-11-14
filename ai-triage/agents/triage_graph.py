"""
AIST LangGraph 0.2 Multi-Agent Triage Swarm with Human-in-the-Loop (HITL)
Primary AI Model: ornith-1.5:35b (Ollama with 100% GPU offload on RTX 5090)
Uses FastMCP 4.1 tools and LangGraph native interrupt() for safe remediation.
Dynamically tailors diagnostics and remediations to heterogeneous OS targets:
- RHEL 10 (192.168.1.130): TicketFlow Flask API & Notification Service
- RHEL 9  (192.168.1.131): Observability Suite (Prometheus, Loki, AlertManager)
- Win2025 (192.168.1.132): Auth Gateway (.NET / HTTP / IIS)
- Win2019 (192.168.1.133): Audit & SQL Server DB Service
"""

import json
import logging
import os
import sys
import time
import requests
from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

# Add mcp-servers and root directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp-servers")))
from config import (
    OLLAMA_HOST, PRIMARY_LLM,
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP
)
from mcp_server import TOOLS
from remediation_policy import get_remediation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("triage_graph")

OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"


class TriageState(TypedDict):
    incident_id: str
    alert_payload: Dict[str, Any]
    user_query: str
    diagnostics_log: List[Dict[str, Any]]
    thought_stream: str
    root_cause_analysis: str
    proposed_remediation: Optional[Dict[str, Any]]
    remediation_status: str
    final_report: str


def call_llm(prompt: str, system_prompt: str = "") -> str:
    """Helper to query local Ollama LLM with optimal 16k context on RTX 5090."""
    effective_system = system_prompt or (
        "You are the Principal SRE Incident Commander for a hybrid enterprise infrastructure. "
        "Keep internal thinking concise inside <think>...</think> and immediately output the structured SRE report: "
        "# Executive Summary, # Chronological Event Timeline (Markdown table), # Root Cause Correlation, # Remediation Action."
    )
    payload = {
        "model": PRIMARY_LLM,
        "prompt": prompt,
        "system": effective_system,
        "options": {
            "num_ctx": 16384,
            "num_predict": 4096,
            "temperature": 0.1
        },
        "stream": False
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return f"LLM Inference Error: {str(e)}"


# --- Node 1: Triage Coordinator ---
def triage_coordinator(state: TriageState) -> Dict[str, Any]:
    logger.info("TriageCoordinator evaluating incident %s", state.get("incident_id"))
    alert = state.get("alert_payload", {})
    query = state.get("user_query", "")

    prompt = f"""You are the Lead SRE Incident Coordinator.
Incident Details:
Alert Payload: {json.dumps(alert, indent=2)}
User Query / Symptom: {query}

Determine which diagnostic tools should be invoked first:
- mcp_prometheus.query: For time-series metrics
- mcp_loki.query_logs: For application & system logs from Loki
- mcp_linux_diag.run_ssh: For RHEL 10 / RHEL 9 system diagnostics
- mcp_windows_diag.run_powershell: For Windows Server 2025 / 2019 diagnostics
- mcp_vcenter.status: For hypervisor / datastore health
- mcp_kb.search_runbooks: For matching SRE runbooks

Think systematically through the causality and determine the primary subsystem and operating system at risk.
"""
    reasoning = call_llm(prompt, "You are an expert SRE incident coordinator. Think deeply and systematically.")
    
    # Run initial baseline diagnostic telemetry
    active_alerts = TOOLS["mcp_prometheus.active_alerts"]()
    vcenter_health = TOOLS["mcp_vcenter.status"]()

    diagnostics = state.get("diagnostics_log", [])
    diagnostics.append({"tool": "mcp_prometheus.active_alerts", "result": active_alerts})
    diagnostics.append({"tool": "mcp_vcenter.status", "result": f"Connected, {len(vcenter_health.get('vms', []))} VMs discovered on Base_DS"})

    return {
        "thought_stream": reasoning,
        "diagnostics_log": diagnostics
    }


# --- Node 2: Multi-OS Telemetry & Diagnostic Specialist ---
def os_diagnostics_specialist(state: TriageState) -> Dict[str, Any]:
    logger.info("OS Diagnostics Specialist running on incident %s", state.get("incident_id"))
    alert = state.get("alert_payload", {})
    query = state.get("user_query", "").lower()
    target_os = str(alert.get("target_os", "")).lower()
    diagnostics = state.get("diagnostics_log", [])

    # Route diagnostics strictly based on target OS
    if "win2025" in target_os or "2025" in query or "iis" in query or "auth" in query:
        # Windows Server 2025 Auth Gateway diagnostics via WinRM
        ps_res = TOOLS["mcp_windows_diag.run_powershell"](
            host=WIN2025_IP,
            script="Get-Process | Where-Object { $_.ProcessName -match 'powershell|w3wp' } | Select-Object -First 5 ProcessName, Id, CPU; Test-NetConnection -Port 5001 -ComputerName 127.0.0.1 | Select-Object TcpTestSucceeded; Get-Content 'C:\\AIST\\AuthGateway\\auth_gateway.log' -Tail 5 -ErrorAction SilentlyContinue"
        )
        diagnostics.append({"tool": "mcp_windows_diag.win2025", "host": WIN2025_IP, "result": ps_res})

    elif "win2019" in target_os or "2019" in query or "sql" in query or "deadlock" in query:
        # Windows Server 2019 Database & Audit Service diagnostics via WinRM
        ps_res = TOOLS["mcp_windows_diag.run_powershell"](
            host=WIN2019_IP,
            script="Get-Process | Where-Object { $_.ProcessName -match 'sql|powershell' } | Select-Object -First 5 ProcessName, Id; Get-Content 'C:\\AIST\\AuditService\\audit_service.log' -Tail 5 -ErrorAction SilentlyContinue"
        )
        diagnostics.append({"tool": "mcp_windows_diag.win2019", "host": WIN2019_IP, "result": ps_res})

    elif "rhel9" in target_os or "observability" in query or "prometheus" in query:
        # RHEL 9 Observability Host via SSH
        ssh_res = TOOLS["mcp_linux_diag.run_ssh"](
            host=RHEL9_IP,
            command="uptime; podman ps --format '{{.Names}}: {{.Status}}'"
        )
        diagnostics.append({"tool": "mcp_linux_diag.rhel9", "host": RHEL9_IP, "result": ssh_res})

    else:
        # RHEL 10 TicketFlow & Notification Services via SSH
        ssh_res = TOOLS["mcp_linux_diag.run_ssh"](
            host=RHEL10_IP,
            command="uptime; free -m; ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu | head -6"
        )
        diagnostics.append({"tool": "mcp_linux_diag.rhel10", "host": RHEL10_IP, "result": ssh_res})

    # Query Knowledge Base for matching SRE Runbooks
    search_term = alert.get("alertname", query if query else "service incident")
    kb_res = TOOLS["mcp_kb.search_runbooks"](search_term)
    diagnostics.append({"tool": "mcp_kb.search_runbooks", "result": kb_res})

    return {"diagnostics_log": diagnostics}


# --- Node 3: Synthesis & Dynamic RCA Generation ---
def rca_synthesis_node(state: TriageState) -> Dict[str, Any]:
    logger.info("Synthesizing Root Cause Analysis report...")
    alert = state.get("alert_payload", {})
    query = state.get("user_query", "").lower()
    target_os = str(alert.get("target_os", "")).lower()
    diag_summary = json.dumps(state.get("diagnostics_log", []), indent=2)

    prompt = f"""You are the Principal SRE Incident Commander.
Synthesize the observed telemetry, diagnostics, and runbooks into an executive Root Cause Analysis (RCA) report:

Alert Payload:
{json.dumps(alert, indent=2)}

Incident Query:
{state.get("user_query", "")}

Diagnostic Evidence Gathered:
{diag_summary}

Requirements:
1. Executive Incident Summary
2. Timeline of Causality (identify the FIRST component to fail vs downstream symptoms)
3. Technical Root Cause with telemetry proof
4. Concrete Proposed Remediation Action

Output the report in clean GitHub-flavored Markdown.
"""
    rca_report = call_llm(prompt)
    
    # Select a server-side allowlisted remediation.  The LLM creates the RCA,
    # never a command that may be executed.
    if "win2025" in target_os or "2025" in query or "iis" in query or "auth" in query:
        proposed_action = get_remediation("recover_auth_gateway")
    elif "win2019" in target_os or "2019" in query or "sql" in query or "deadlock" in query:
        proposed_action = get_remediation("recover_sql_lock")
    elif "queue" in query:
        proposed_action = get_remediation("recover_notification_queue")
    elif "cpu" in query:
        proposed_action = get_remediation("stop_synthetic_cpu_stress_rhel10")
    else:
        proposed_action = None

    return {
        "root_cause_analysis": rca_report,
        "proposed_remediation": proposed_action
    }


# --- Node 4: Human-in-the-Loop Remediation Review ---
def human_review_node(state: TriageState) -> Dict[str, Any]:
    logger.info("Gating remediation behind human approval...")
    remediation = state.get("proposed_remediation", {})
    if not remediation:
        return {
            "remediation_status": "NO_SAFE_AUTOMATION_AVAILABLE",
            "final_report": state.get("root_cause_analysis", "") + "\n\n### Remediation Status\nNo allowlisted remediation matches this incident. Escalate with the collected evidence."
        }
    
    # Trigger native LangGraph interrupt to pause execution and prompt SRE
    approval_result = interrupt({
        "prompt": "Remediation Action Proposed by AI Triage Agent",
        "action_id": remediation.get("id"),
        "action": remediation.get("action_type"),
        "target": remediation.get("target_server"),
        "blast_radius": remediation.get("blast_radius"),
        "instructions": "Approve execution via Command(resume='approved') or Reject via Command(resume='rejected')"
    })

    if approval_result == "approved":
        logger.info("Remediation APPROVED by human SRE. Executing on target host...")
        target_node = remediation.get("target_server", "RHEL10")
        cmd = remediation.get("command", "")
        verification_cmd = remediation.get("verification", "")
        host_ip = {"WIN2025": WIN2025_IP, "WIN2019": WIN2019_IP, "RHEL9": RHEL9_IP, "RHEL10": RHEL10_IP}.get(target_node, RHEL10_IP)

        exec_output = ""
        verification_output = "not_run"
        status = "EXECUTED_SUCCESSFULLY"
        try:
            if "WIN" in target_node:
                res = TOOLS["mcp_windows_diag.run_powershell"](host=host_ip, script=cmd)
                exec_output = res.get("stdout", "") or res.get("stderr", "") or res.get("status", "")
                if res.get("status") != "success":
                    raise RuntimeError(res.get("error") or res.get("stderr") or "Windows remediation failed")
                verify_res = TOOLS["mcp_windows_diag.run_powershell"](host=host_ip, script=verification_cmd)
            else:
                res = TOOLS["mcp_linux_diag.run_ssh"](host=host_ip, command=cmd)
                exec_output = res.get("stdout", "") or res.get("stderr", "") or res.get("status", "")
                if res.get("status") != "success":
                    raise RuntimeError(res.get("error") or res.get("stderr") or "Linux remediation failed")
                verify_res = TOOLS["mcp_linux_diag.run_ssh"](host=host_ip, command=verification_cmd)
            verification_output = verify_res.get("stdout", "") or verify_res.get("stderr", "") or verify_res.get("status", "no output")
            if verify_res.get("status") != "success":
                status = "VERIFY_FAILED"
        except Exception as e:
            status = "FAILED"
            exec_output = f"Execution error: {str(e)}"

        return {
            "remediation_status": status,
            "final_report": state.get("root_cause_analysis", "") + (
                f"\n\n### Remediation {status} on {target_node}\n"
                f"Action: {remediation.get('title', remediation.get('id'))} "
                f"(`{remediation.get('id')}`)\n\n"
                f"**Output:**\n```text\n{exec_output}\n```\n\n"
                f"**Verification:**\n```text\n{verification_output}\n```"
            ),
        }
    else:
        logger.warning("Remediation REJECTED or CANCELLED by human SRE.")
        return {
            "remediation_status": "REJECTED_BY_USER",
            "final_report": state.get("root_cause_analysis", "") + "\n\n### ⏸️ Remediation Status\nAction was reviewed and cancelled by SRE operator. No system changes were executed."
        }


# --- Build StateGraph ---
def build_triage_graph():
    # pyrefly: ignore[bad-specialization]
    workflow = StateGraph(TriageState)

    workflow.add_node("triage_coordinator", triage_coordinator)
    workflow.add_node("os_diagnostics_specialist", os_diagnostics_specialist)
    workflow.add_node("rca_synthesis_node", rca_synthesis_node)
    workflow.add_node("human_review_node", human_review_node)

    workflow.add_edge(START, "triage_coordinator")
    workflow.add_edge("triage_coordinator", "os_diagnostics_specialist")
    workflow.add_edge("os_diagnostics_specialist", "rca_synthesis_node")
    workflow.add_edge("rca_synthesis_node", "human_review_node")
    workflow.add_edge("human_review_node", END)

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


if __name__ == "__main__":
    print("Compiling LangGraph Multi-Agent Triage Swarm...")
    graph = build_triage_graph()
    print("Graph compiled successfully with checkpointer persistence!")
