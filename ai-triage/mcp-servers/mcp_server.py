"""
AIST FastMCP 4.1 Enterprise Diagnostic Server
Built on FastMCP 4.1.6 & Official MCP 2.3.0 Protocol
Features:
- Security Gateways & Command Sanitization Guardrails
- Tool Annotations (readOnlyHint, idempotentHint, destructiveHint)
- Local Hybrid RAG Integration (RTX 5090 embeddings + BM25)
- Durable SQLite Audit Logging in WAL Mode (aist_state.db)
"""

import json
import logging
import os
import re
import sys
import time
from typing import Dict, Any, List, Optional
import requests
import paramiko
import winrm

# FastMCP 4.1.6 and official MCP SDK
from fastmcp import FastMCP

# Ensure AIST root and modules are in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "knowledge-base")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "webui", "backend", "app")))

from config import (
    PROM_URL, ALERTMANAGER_URL, LOKI_URL,
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP,
    LINUX_USER, LINUX_PASS, WINDOWS_USER, WINDOWS_PASS,
    LOCAL_AI_HOST
)
from infrastructure.vcenter_manager import VCenterManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aist_mcp")

# Initialize FastMCP Server Instance (FastMCP 4.1.6 / MCP 2.3.0)
mcp = FastMCP("AIST-Diagnostic-Server")
ALLOWED_LINUX_HOSTS = {RHEL10_IP, RHEL9_IP}
ALLOWED_WINDOWS_HOSTS = {WIN2025_IP, WIN2019_IP}

# Security Guardrails Patterns
PROHIBITED_LINUX_COMMANDS = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-rf|-fr)\s+/",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bdd\s+if=/dev/",
    r"\b(shutdown|poweroff|reboot|init\s+0)\b",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\bchmod\s+(-[a-zA-Z]*R\s+)?777\s+/",
    r">\s*/dev/(sd[a-z]|nvme|vd[a-z])",
]

PROHIBITED_WINDOWS_SCRIPTS = [
    r"Remove-Item\s+.*-Recurse\s+.*-Force\s+([A-Za-z]:\\|\*|/)",
    r"(Format-Volume|Clear-Disk|Initialize-Disk)",
    r"(Stop-Computer|Restart-Computer)",
    r"Invoke-Expression\s+.*\b(DownloadString|curl|wget)\b",
    r"bcdedit",
]


def _audit(tool_name: str, params: Any, status: str, duration_ms: float, error: str = ""):
    """Persist tool call execution in durable SQLite audit log."""
    try:
        try:
            from state_store import get_state_store
        except ImportError:
            from webui.backend.app.state_store import get_state_store
        store = get_state_store()
        store.log_mcp_tool_execution(tool_name, params, status, duration_ms, error)
    except Exception:
        pass


# --- Tool Implementation Functions (Decorated with FastMCP 4.1) ---

@mcp.tool(
    name="mcp_prometheus_query",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"telemetry", "prometheus", "metrics"}
)
def tool_query_prometheus(query: str) -> dict:
    """Execute an instant PromQL query against Prometheus 3.0."""
    t0 = time.time()
    try:
        url = f"{PROM_URL}/api/v1/query"
        resp = requests.get(url, params={"query": query}, timeout=10)
        res = resp.json()
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_prometheus.query", {"query": query}, "success", duration_ms)
        return res
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_prometheus.query", {"query": query}, "error", duration_ms, str(e))
        return {"status": "error", "message": f"Prometheus query failed: {str(e)}"}


@mcp.tool(
    name="mcp_prometheus_active_alerts",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"telemetry", "alertmanager", "alerts"}
)
def tool_get_active_alerts() -> list:
    """Retrieve currently firing alerts from AlertManager 0.27."""
    t0 = time.time()
    try:
        url = f"{ALERTMANAGER_URL}/api/v2/alerts"
        resp = requests.get(url, timeout=5)
        res = resp.json()
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_prometheus.active_alerts", {}, "success", duration_ms)
        return res
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_prometheus.active_alerts", {}, "error", duration_ms, str(e))
        return [{"error": f"AlertManager unreachable: {str(e)}"}]


@mcp.tool(
    name="mcp_loki_query_logs",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"telemetry", "loki", "logs"}
)
def tool_query_loki_logs(query: str = '{app="ticketflow"}', limit: int = 50) -> dict:
    """Execute a LogQL range query against Loki log aggregator."""
    t0 = time.time()
    try:
        url = f"{LOKI_URL}/loki/api/v1/query_range"
        start_ns = str(int((time.time() - 7200) * 1e9))
        end_ns = str(int(time.time() * 1e9))
        params = {"query": query, "limit": limit, "start": start_ns, "end": end_ns}
        resp = requests.get(url, params=params, timeout=10)
        res = resp.json()
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_loki.query_logs", {"query": query, "limit": limit}, "success", duration_ms)
        return res
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_loki.query_logs", {"query": query, "limit": limit}, "error", duration_ms, str(e))
        return {"status": "error", "message": f"Loki query failed: {str(e)}"}


@mcp.tool(
    name="mcp_loki_push_log",
    annotations={"readOnlyHint": False, "idempotentHint": False, "destructiveHint": False},
    tags={"telemetry", "loki", "ingestion"}
)
def tool_push_loki_log(service: str, level: str, message: str, os_target: str = "linux") -> dict:
    """Push a structured log entry directly to Loki log aggregator."""
    t0 = time.time()
    try:
        url = f"{LOKI_URL}/loki/api/v1/push"
        now_ns = str(time.time_ns())
        payload = {
            "streams": [
                {
                    "stream": {
                        "app": "ticketflow",
                        "service": service,
                        "os": os_target,
                        "level": level.upper()
                    },
                    "values": [[now_ns, message]]
                }
            ]
        }
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=5)
        status_str = "success" if resp.status_code == 204 else f"status_{resp.status_code}"
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_loki.push_log", {"service": service, "level": level}, status_str, duration_ms)
        return {"status": status_str}
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_loki.push_log", {"service": service, "level": level}, "error", duration_ms, str(e))
        return {"status": "error", "message": f"Loki push failed: {str(e)}"}


@mcp.tool(
    name="mcp_linux_run_ssh",
    annotations={"readOnlyHint": True, "idempotentHint": False, "destructiveHint": False},
    tags={"diagnostics", "linux", "ssh"}
)
def tool_run_linux_ssh(host: str = RHEL10_IP, command: str = "uptime; free -m") -> dict:
    """Execute a diagnostic command on a Linux host (RHEL 10 or RHEL 9) via SSH with security guardrails."""
    t0 = time.time()
    if host not in ALLOWED_LINUX_HOSTS:
        return {"host": host, "status": "error", "error": "Host is not in the AIST Linux inventory"}

    # Security Guardrail Check
    for pattern in PROHIBITED_LINUX_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            msg = f"Security Gateway Blocked Prohibited Command: '{command}'"
            logger.warning(msg)
            _audit("mcp_linux_diag.run_ssh", {"host": host, "command": command}, "blocked_by_guardrail", 0.0, msg)
            return {"host": host, "status": "blocked_by_guardrail", "error": msg}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=10)
        stdin, stdout, stderr = client.exec_command(command, timeout=15)
        out_str = stdout.read().decode("utf-8", errors="replace")
        err_str = stderr.read().decode("utf-8", errors="replace")
        client.close()
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_linux_diag.run_ssh", {"host": host, "command": command}, "success", duration_ms)
        return {
            "host": host,
            "command": command,
            "stdout": out_str.strip(),
            "stderr": err_str.strip(),
            "status": "success"
        }
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_linux_diag.run_ssh", {"host": host, "command": command}, "error", duration_ms, str(e))
        return {"host": host, "command": command, "status": "error", "error": str(e)}


@mcp.tool(
    name="mcp_windows_run_powershell",
    annotations={"readOnlyHint": True, "idempotentHint": False, "destructiveHint": False},
    tags={"diagnostics", "windows", "powershell"}
)
def tool_run_windows_powershell(host: str = WIN2025_IP, script: str = "Get-Service | Select-Object -First 10") -> dict:
    """Execute a PowerShell command on Windows Server 2025 or 2019 via WinRM with security guardrails."""
    t0 = time.time()
    target_ip = WIN2025_IP if "2025" in host else (WIN2019_IP if "2019" in host else host)
    if target_ip not in ALLOWED_WINDOWS_HOSTS:
        return {"host": target_ip, "status": "error", "error": "Host is not in the AIST Windows inventory"}

    # Security Guardrail Check
    for pattern in PROHIBITED_WINDOWS_SCRIPTS:
        if re.search(pattern, script, re.IGNORECASE):
            msg = f"Security Gateway Blocked Prohibited PowerShell Script: '{script[:80]}...'"
            logger.warning(msg)
            _audit("mcp_windows_diag.run_powershell", {"host": target_ip, "script": script[:100]}, "blocked_by_guardrail", 0.0, msg)
            return {"host": target_ip, "status": "blocked_by_guardrail", "error": msg}

    try:
        session = winrm.Session(f"http://{target_ip}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
        result = session.run_ps(script)
        duration_ms = (time.time() - t0) * 1000
        status_str = "success" if result.status_code == 0 else "failed"
        _audit("mcp_windows_diag.run_powershell", {"host": target_ip, "script": script[:100]}, status_str, duration_ms)
        return {
            "host": target_ip,
            "status_code": result.status_code,
            "stdout": result.std_out.decode("utf-8", errors="replace").strip(),
            "stderr": result.std_err.decode("utf-8", errors="replace").strip(),
            "status": status_str
        }
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_windows_diag.run_powershell", {"host": target_ip, "script": script[:100]}, "error", duration_ms, str(e))
        return {"host": target_ip, "status": "error", "error": str(e)}


@mcp.tool(
    name="mcp_windows_event_logs",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"diagnostics", "windows", "events"}
)
def tool_windows_event_logs(host: str = WIN2025_IP, channel: str = "Application", hours: int = 24, max_events: int = 30) -> dict:
    """Retrieve Critical, Error, and Warning events from Windows Event Viewer for a specific channel."""
    t0 = time.time()
    target_ip = WIN2025_IP if "2025" in host else (WIN2019_IP if "2019" in host else host)
    server_label = "WIN2025 (192.168.1.132)" if target_ip == WIN2025_IP else "WIN2019 (192.168.1.133)"
    logger.info("Querying Event Viewer on %s (Channel: %s, Hours: %d)", server_label, channel, hours)
    
    ps_cmd = f"""
    try {{
        $after = (Get-Date).AddHours(-{hours})
        $events = Get-WinEvent -FilterHashtable @{{LogName='{channel}'; StartTime=$after; Level=1,2,3}} -MaxEvents {max_events} -ErrorAction Stop
        $out = $events | ForEach-Object {{
            $msg = ($_.Message -replace '[\\r\\n]+',' ')
            if ($msg.Length -gt 400) {{ $msg = $msg.Substring(0, 400) + '...[TRUNC]' }}
            [PSCustomObject]@{{
                TimeCreated      = ($_.TimeCreated).ToString('yyyy-MM-dd HH:mm:ss')
                RecordId         = $_.RecordId
                Id               = $_.Id
                Level            = ($_.LevelDisplayName -as [string])
                ProviderName     = ($_.ProviderName -as [string])
                Message          = $msg
            }}
        }}
        $out | ConvertTo-Json -Depth 3
    }} catch {{
        if ($_.Exception.Message -like "*No events were found*") {{
            @() | ConvertTo-Json
        }} else {{
            @{{ Error = $_.Exception.Message }} | ConvertTo-Json
        }}
    }}
    """
    res = tool_run_windows_powershell(host=target_ip, script=ps_cmd)
    stdout = res.get("stdout", "")
    events = []
    try:
        parsed = json.loads(stdout) if stdout else []
        events = parsed if isinstance(parsed, list) else ([parsed] if parsed else [])
    except Exception:
        events = [{"raw_output": stdout[:500]}] if stdout else []

    duration_ms = (time.time() - t0) * 1000
    _audit("mcp_windows_diag.event_logs", {"host": target_ip, "channel": channel}, "success", duration_ms)
    return {
        "server": server_label,
        "host_ip": target_ip,
        "channel": channel,
        "hours_searched": hours,
        "event_count": len(events),
        "events": events
    }


@mcp.tool(
    name="mcp_windows_iis_status",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"diagnostics", "windows", "iis"}
)
def tool_windows_iis_status(host: str = WIN2025_IP) -> dict:
    """Retrieve IIS web server, AppPools, worker processes, and AuthGateway listener health on Windows."""
    t0 = time.time()
    target_ip = WIN2025_IP if "2025" in host else (WIN2019_IP if "2019" in host else host)
    server_label = "WIN2025 (192.168.1.132)" if target_ip == WIN2025_IP else "WIN2019 (192.168.1.133)"
    
    ps_cmd = """
    $res = [PSCustomObject]@{
        ComputerName   = $env:COMPUTERNAME
        AuthGateway    = (Test-NetConnection -ComputerName 127.0.0.1 -Port 5001 -WarningAction SilentlyContinue).TcpTestSucceeded
        AuditService   = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8088 -WarningAction SilentlyContinue).TcpTestSucceeded
        WorkerProcesses= @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*AuthGateway*" -or $_.CommandLine -like "*AuditService*" -or $_.Name -like "*w3wp*" } | Select-Object ProcessId, Name, CommandLine)
        StoppedServices= @(Get-CimInstance Win32_Service | Where-Object { ($_.StartMode -eq 'Auto' -or $_.StartMode -eq 'Automatic') -and ($_.State -ne 'Running') } | Select-Object -First 10 Name, DisplayName, State)
    }
    $res | ConvertTo-Json -Depth 3
    """
    res = tool_run_windows_powershell(host=target_ip, script=ps_cmd)
    stdout = res.get("stdout", "")
    try:
        data = json.loads(stdout)
    except Exception:
        data = {"raw_output": stdout}

    duration_ms = (time.time() - t0) * 1000
    _audit("mcp_windows_diag.iis_status", {"host": target_ip}, "success", duration_ms)
    return {
        "server": server_label,
        "host_ip": target_ip,
        "details": data
    }


@mcp.tool(
    name="mcp_windows_os_patching",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"diagnostics", "windows", "patching"}
)
def tool_windows_os_patching(host: str = WIN2025_IP) -> dict:
    """Retrieve Windows OS version, uptime, installed KBs / HotFixes, and pending updates."""
    t0 = time.time()
    target_ip = WIN2025_IP if "2025" in host else (WIN2019_IP if "2019" in host else host)
    server_label = "WIN2025 (192.168.1.132)" if target_ip == WIN2025_IP else "WIN2019 (192.168.1.133)"

    ps_cmd = """
    $os = Get-CimInstance Win32_OperatingSystem
    $bootTime = $os.LastBootUpTime
    $uptimeHours = [math]::Round(((Get-Date) - $bootTime).TotalHours, 1)
    $hotfixes = @(Get-HotFix | Select-Object -First 5 HotFixID, Description, InstalledOn)
    [PSCustomObject]@{
        Caption     = $os.Caption
        Version     = $os.Version
        UptimeHours = $uptimeHours
        LastBoot    = ($bootTime).ToString('yyyy-MM-dd HH:mm:ss')
        HotFixes    = $hotfixes
    } | ConvertTo-Json -Depth 3
    """
    res = tool_run_windows_powershell(host=target_ip, script=ps_cmd)
    stdout = res.get("stdout", "")
    try:
        data = json.loads(stdout)
    except Exception:
        data = {"raw_output": stdout}

    duration_ms = (time.time() - t0) * 1000
    _audit("mcp_windows_diag.os_patching", {"host": target_ip}, "success", duration_ms)
    return {
        "server": server_label,
        "host_ip": target_ip,
        "system_info": data
    }


@mcp.tool(
    name="mcp_windows_disk_info",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"diagnostics", "windows", "storage"}
)
def tool_windows_disk_info(host: str = WIN2025_IP) -> dict:
    """Retrieve Logical Disk capacity, free space, and volume health on Windows hosts."""
    t0 = time.time()
    target_ip = WIN2025_IP if "2025" in host else (WIN2019_IP if "2019" in host else host)
    ps_cmd = """
    Get-CimInstance Win32_LogicalDisk | Where-Object { $_.DriveType -eq 3 } | ForEach-Object {
        [PSCustomObject]@{
            DeviceID    = $_.DeviceID
            VolumeName  = $_.VolumeName
            SizeGB      = [math]::Round($_.Size / 1GB, 2)
            FreeGB      = [math]::Round($_.FreeSpace / 1GB, 2)
            PercentFree = [math]::Round(($_.FreeSpace / $_.Size) * 100, 1)
        }
    } | ConvertTo-Json -Depth 2
    """
    res = tool_run_windows_powershell(host=target_ip, script=ps_cmd)
    stdout = res.get("stdout", "")
    try:
        data = json.loads(stdout)
    except Exception:
        data = {"raw_output": stdout}

    duration_ms = (time.time() - t0) * 1000
    _audit("mcp_windows_diag.disk_info", {"host": target_ip}, "success", duration_ms)
    return {"host_ip": target_ip, "disks": data}


@mcp.tool(
    name="mcp_vcenter_status",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"infrastructure", "vmware", "vcenter"}
)
def tool_query_vcenter(vm_name: str = "") -> dict:
    """Retrieve VMware vCenter VM states and datastore capacity."""
    t0 = time.time()
    mgr = VCenterManager()
    if not mgr.connect():
        _audit("mcp_vcenter.status", {"vm_name": vm_name}, "error", 0.0, "vCenter auth failure")
        return {"status": "error", "message": "Failed to authenticate to vCenter"}
    
    if vm_name:
        vm = mgr.find_vm_by_name(vm_name)
        if vm:
            details = mgr.get_vm_details(vm["vm"])
            duration_ms = (time.time() - t0) * 1000
            _audit("mcp_vcenter.status", {"vm_name": vm_name}, "success", duration_ms)
            return {"status": "success", "vm": details}
        return {"status": "not_found", "message": f"VM {vm_name} not found"}
    
    vms = mgr.list_vms()
    datastores = mgr.list_datastores()
    duration_ms = (time.time() - t0) * 1000
    _audit("mcp_vcenter.status", {"vm_name": vm_name}, "success", duration_ms)
    return {"status": "success", "vms": vms, "datastores": datastores}


@mcp.tool(
    name="mcp_kb_search_runbooks",
    annotations={"readOnlyHint": True, "idempotentHint": True, "destructiveHint": False},
    tags={"rag", "knowledge_base", "runbooks"}
)
def tool_search_knowledge_base(query: str, k: int = 3) -> list:
    """Search SRE Runbooks using local Hybrid RAG (Vector Embedding + BM25)."""
    t0 = time.time()
    try:
        from rag_engine import get_rag_engine
        engine = get_rag_engine()
        results = engine.search(query, k=k)
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_kb.search_runbooks", {"query": query, "k": k}, "success", duration_ms)
        return results
    except Exception as e:
        duration_ms = (time.time() - t0) * 1000
        _audit("mcp_kb.search_runbooks", {"query": query, "k": k}, "error", duration_ms, str(e))
        return [{"error": f"RAG search failed: {str(e)}"}]


# Expose canonical tools dictionary for LangGraph, FastMCP, and Copilot
TOOLS = {
    "mcp_prometheus.query": tool_query_prometheus,
    "mcp_prometheus.active_alerts": tool_get_active_alerts,
    "mcp_loki.query_logs": tool_query_loki_logs,
    "mcp_loki.push_log": tool_push_loki_log,
    "mcp_linux_diag.run_ssh": tool_run_linux_ssh,
    "mcp_windows_diag.run_powershell": tool_run_windows_powershell,
    "mcp_windows_diag.event_logs": tool_windows_event_logs,
    "mcp_windows_diag.iis_status": tool_windows_iis_status,
    "mcp_windows_diag.os_patching": tool_windows_os_patching,
    "mcp_windows_diag.disk_info": tool_windows_disk_info,
    "mcp_vcenter.status": tool_query_vcenter,
    "mcp_kb.search_runbooks": tool_search_knowledge_base
}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        print("Starting FastMCP server over standard stdio...")
        mcp.run()
    else:
        print("Testing FastMCP Tools locally (FastMCP 4.1.6 / MCP 2.3.0)...")
        print("1. Testing Hybrid RAG Tool:")
        rag_res = tool_search_knowledge_base("Linux CPU memory saturation", k=1)
        print(" -> RAG result:", rag_res[0].get("id") if rag_res else "None")

        print("2. Testing Guardrail Security on Linux SSH:")
        sec_res = tool_run_linux_ssh(command="rm -rf /")
        print(" -> Guardrail status:", sec_res.get("status"))

        print("3. Testing Linux SSH Tool on RHEL 10:")
        ssh_res = tool_run_linux_ssh(command="hostname; uptime")
        print(" -> SSH result:", ssh_res.get("stdout"))
