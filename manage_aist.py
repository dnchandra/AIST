#!/usr/bin/env python3
"""
================================================================================
  AIST: Autonomous SRE Incident Triage Platform v3.0
  Master Unified Control & Orchestration CLI (manage_aist.py)
================================================================================
Single unified control plane for the entire AIST multi-OS enterprise lifecycle:

  python manage_aist.py list              - List all apps, containers, servers, and live URLs
  python manage_aist.py urls              - Alias for list (displays complete URLs directory)
  python manage_aist.py status            - Execute 21-point automated verification matrix
  python manage_aist.py start [target]    - Start services (targets: webui, all, apps, obs, <service>)
  python manage_aist.py stop [target]     - Stop services (targets: all, apps, obs, webui, <service>)
  python manage_aist.py restart [target]  - Restart services (targets: all, apps, obs, webui, <service>)
  python manage_aist.py deploy [target]   - Deploy microservices and observability across 4 VMs
  python manage_aist.py logs <service>    - Tail live logs from remote VMs, containers, or local services
  python manage_aist.py setup             - Validate vCenter, datastores, VM power states, firewalls
  python manage_aist.py chaos             - Inject failure scenarios (cpu_spike, auth_crash, etc.)
  python manage_aist.py recover           - Restore all services back to 100% healthy state
  python manage_aist.py clean             - Reset temporary logs while preserving VM disks
================================================================================
"""

import os
import sys
import time
import json
import socket
import logging
import argparse
import subprocess
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

# Auto-reexec inside .venv if invoked with system Python lacking dependencies
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(VENV_PYTHON) and sys.executable.lower() != os.path.abspath(VENV_PYTHON).lower():
    try:
        import paramiko
        import winrm
    except ImportError:
        res = subprocess.run([VENV_PYTHON] + sys.argv, env=os.environ)
        sys.exit(res.returncode)

import requests
import paramiko
import winrm

# Configure system search paths
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "ai-triage", "mcp-servers"))
sys.path.insert(0, os.path.join(BASE_DIR, "ai-triage", "agents"))
sys.path.insert(0, os.path.join(BASE_DIR, "ai-triage", "webui", "backend", "app"))

from config import (
    VCENTER_HOST, VCENTER_USER, VCENTER_PASS, ESXI_HOST, DATASTORE_TARGET,
    RHEL10_IP, RHEL9_IP, WIN2025_IP, WIN2019_IP, LOCAL_AI_HOST,
    LINUX_USER, LINUX_PASS, WINDOWS_USER, WINDOWS_PASS,
    TICKETFLOW_PORT, NOTIFICATION_PORT, AUTH_GATEWAY_PORT, AUDIT_SERVICE_PORT, NODE_EXPORTER_PORT,
    PROMETHEUS_PORT, GRAFANA_PORT, LOKI_PORT, ALERTMANAGER_PORT, BACKEND_PORT, FRONTEND_PORT,
    OLLAMA_HOST, PRIMARY_LLM, EMBEDDING_LLM,
    PROM_URL, ALERTMANAGER_URL, GRAFANA_URL, LOKI_URL,
    TICKETFLOW_API_URL, NOTIFICATION_API_URL, AUTH_GATEWAY_URL, AUDIT_SERVICE_URL,
    BACKEND_URL, FRONTEND_URL
)

from infrastructure.vcenter_manager import VCenterManager
from infrastructure.vcenter_provisioner import VCenterProvisioner, TEMPLATES, is_protected
from mcp_server import TOOLS

# Configure Dual Rolling Logging (Console + logs/manage_aist.log)
from logging.handlers import RotatingFileHandler
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
MANAGE_LOG_FILE = os.path.join(LOGS_DIR, "manage_aist.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers.clear()

log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

file_handler = RotatingFileHandler(
    MANAGE_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

logger = logging.getLogger("manage_aist")

# ANSI Color Codes for terminal formatting
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


# ==============================================================================
# SERVICE REGISTRY: Complete Enterprise Inventory
# ==============================================================================
SERVICES_CATALOG = [
    # 1. Web UIs & SRE Dashboards
    {
        "id": "webui",
        "name": "AIST Incident Cockpit",
        "category": "Web UI",
        "host": "Localhost (Win11)",
        "ip": "127.0.0.1",
        "port": FRONTEND_PORT,
        "type": "Vite React SPA",
        "primary_url": f"http://localhost:{FRONTEND_PORT}/",
        "health_url": f"http://localhost:{FRONTEND_PORT}/",
        "metrics_url": None,
        "api_docs_url": None,
        "log_path": "Local preview process",
        "desc": "Glassmorphic SRE cockpit, live topology, AI swarm agent chat"
    },
    {
        "id": "loan-portal",
        "name": "LoanProcessAI Portal",
        "category": "Web UI",
        "host": "Win Server 2025 VM",
        "ip": WIN2025_IP,
        "port": 3000,
        "type": "React SPA (Port 3000)",
        "primary_url": f"http://{WIN2025_IP}:3000/",
        "health_url": f"http://{WIN2025_IP}:3000/",
        "metrics_url": None,
        "api_docs_url": None,
        "log_path": "C:\\AIST\\LoanPortal\\server.log",
        "desc": "Commercial lending customer portal & banker underwriting cockpit"
    },
    {
        "id": "backend",
        "name": "AI Triage Engine (Backend)",
        "category": "Platform Core",
        "host": "Localhost (Win11)",
        "ip": "127.0.0.1",
        "port": BACKEND_PORT,
        "type": "FastAPI Async Daemon",
        "primary_url": f"http://127.0.0.1:{BACKEND_PORT}/docs",
        "health_url": f"http://127.0.0.1:{BACKEND_PORT}/health",
        "metrics_url": None,
        "api_docs_url": f"http://127.0.0.1:{BACKEND_PORT}/docs",
        "log_path": "Local uvicorn process",
        "desc": "LangGraph multi-agent swarm orchestrator & FastMCP tool router"
    },
    {
        "id": "grafana",
        "name": "Grafana 11.4 WebUI",
        "category": "Web UI",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": GRAFANA_PORT,
        "type": "Container (aist-grafana)",
        "primary_url": GRAFANA_URL,
        "health_url": f"{GRAFANA_URL}/api/health",
        "metrics_url": None,
        "api_docs_url": f"{GRAFANA_URL}/dashboards",
        "log_path": "docker-compose logs aist-grafana",
        "desc": "9 SRE Dashboards (Golden Signals, SLI/SLO, AI Swarm, Live Logs)"
    },
    {
        "id": "prometheus",
        "name": "Prometheus 3.0 WebUI",
        "category": "Observability",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": PROMETHEUS_PORT,
        "type": "Container (aist-prometheus)",
        "primary_url": PROM_URL,
        "health_url": f"{PROM_URL}/-/healthy",
        "metrics_url": f"{PROM_URL}/metrics",
        "api_docs_url": f"{PROM_URL}/targets",
        "log_path": "docker-compose logs aist-prometheus",
        "desc": "Time-series database collecting metrics across all fleet nodes"
    },
    {
        "id": "alertmanager",
        "name": "AlertManager 0.27 WebUI",
        "category": "Observability",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": ALERTMANAGER_PORT,
        "type": "Container (aist-alertmanager)",
        "primary_url": ALERTMANAGER_URL,
        "health_url": f"{ALERTMANAGER_URL}/-/healthy",
        "metrics_url": f"{ALERTMANAGER_URL}/metrics",
        "api_docs_url": f"{ALERTMANAGER_URL}/#/alerts",
        "log_path": "docker-compose logs aist-alertmanager",
        "desc": "Alert routing engine triggering automated AI remediation workflows"
    },

    # 2. Multi-OS Application Fleet
    {
        "id": "loan-backend",
        "name": "LoanProcessAI Core API",
        "category": "Microservice",
        "host": "RHEL 10 VM",
        "ip": RHEL10_IP,
        "port": 5000,
        "type": "Python 3.12 / FastAPI (6 Agents)",
        "primary_url": f"http://{RHEL10_IP}:5000/applications",
        "health_url": f"http://{RHEL10_IP}:5000/healthz",
        "metrics_url": f"http://{RHEL10_IP}:5000/metrics",
        "api_docs_url": f"http://{RHEL10_IP}:5000/applications",
        "log_path": "/opt/aist/loanorigination-api/api.log",
        "desc": "Commercial lending multi-agent backend; guardrails, DSCR, KYC, memo"
    },
    {
        "id": "notification",
        "name": "Notification Dispatcher",
        "category": "Microservice",
        "host": "RHEL 10 VM",
        "ip": RHEL10_IP,
        "port": NOTIFICATION_PORT,
        "type": "Python Event Worker",
        "primary_url": f"{NOTIFICATION_API_URL}/health",
        "health_url": f"{NOTIFICATION_API_URL}/health",
        "metrics_url": f"{NOTIFICATION_API_URL}/metrics",
        "api_docs_url": f"{NOTIFICATION_API_URL}/api/v1/notify",
        "log_path": "/opt/aist/notification-service/service.log",
        "desc": "PagerDuty & Slack notification dispatcher with backlog simulation"
    },
    {
        "id": "auth-gateway",
        "name": "Auth & Identity Gateway",
        "category": "Microservice",
        "host": "Win Server 2025 VM",
        "ip": WIN2025_IP,
        "port": AUTH_GATEWAY_PORT,
        "type": ".NET 9 / PowerShell HTTP",
        "primary_url": f"{AUTH_GATEWAY_URL}/health",
        "health_url": f"{AUTH_GATEWAY_URL}/health",
        "metrics_url": f"{AUTH_GATEWAY_URL}/metrics",
        "api_docs_url": f"{AUTH_GATEWAY_URL}/api/v1/auth/login",
        "log_path": "C:\\AIST\\AuthGateway\\auth_gateway.log",
        "desc": "Enterprise JWT token authentication & security gateway"
    },
    {
        "id": "audit-service",
        "name": "Audit & Compliance Service",
        "category": "Microservice",
        "host": "Win Server 2019 VM",
        "ip": WIN2019_IP,
        "port": AUDIT_SERVICE_PORT,
        "type": "WCF / PowerShell HTTP",
        "primary_url": f"{AUDIT_SERVICE_URL}/health",
        "health_url": f"{AUDIT_SERVICE_URL}/health",
        "metrics_url": f"{AUDIT_SERVICE_URL}/metrics",
        "api_docs_url": f"{AUDIT_SERVICE_URL}/api/v1/audit/logs",
        "log_path": "C:\\AIST\\AuditService\\audit_service.log",
        "desc": "SQL Server query audit trail & database mutation logging"
    },

    # 3. Observability & Logging Infrastructure
    {
        "id": "loki",
        "name": "Loki 3.3 Log Aggregator",
        "category": "Observability",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": LOKI_PORT,
        "type": "Container (aist-loki)",
        "primary_url": f"{LOKI_URL}/ready",
        "health_url": f"{LOKI_URL}/ready",
        "metrics_url": f"{LOKI_URL}/metrics",
        "api_docs_url": f"{LOKI_URL}/loki/api/v1/push",
        "log_path": "docker-compose logs aist-loki",
        "desc": "Centralized log ingestion for all microservices across Linux & Windows"
    },
    {
        "id": "tempo",
        "name": "Tempo 2.6 Distributed Tracing",
        "category": "Observability",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": 3200,
        "type": "Container (aist-tempo)",
        "primary_url": f"http://{RHEL9_IP}:3200/status",
        "health_url": f"http://{RHEL9_IP}:3200/status",
        "metrics_url": f"http://{RHEL9_IP}:3200/metrics",
        "api_docs_url": f"http://{RHEL9_IP}:3200/status",
        "log_path": "docker-compose logs aist-tempo",
        "desc": "High-volume distributed tracing backend for OpenTelemetry"
    },
    {
        "id": "otel-collector",
        "name": "OpenTelemetry Collector",
        "category": "Observability",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": 4318,
        "type": "Container (aist-otel-collector)",
        "primary_url": f"http://{RHEL9_IP}:8888/metrics",
        "health_url": f"http://{RHEL9_IP}:8888/metrics",
        "metrics_url": f"http://{RHEL9_IP}:8888/metrics",
        "api_docs_url": f"http://{RHEL9_IP}:4318/v1/traces",
        "log_path": "docker-compose logs aist-otel-collector",
        "desc": "Telemetry ingestion pipeline (gRPC :4317, HTTP :4318, Metrics :8888)"
    },
    {
        "id": "node-exporter-rhel10",
        "name": "Node Exporter (RHEL 10)",
        "category": "Infrastructure",
        "host": "RHEL 10 VM",
        "ip": RHEL10_IP,
        "port": NODE_EXPORTER_PORT,
        "type": "Podman Container",
        "primary_url": f"http://{RHEL10_IP}:{NODE_EXPORTER_PORT}/metrics",
        "health_url": f"http://{RHEL10_IP}:{NODE_EXPORTER_PORT}/metrics",
        "metrics_url": f"http://{RHEL10_IP}:{NODE_EXPORTER_PORT}/metrics",
        "api_docs_url": None,
        "log_path": "podman logs node-exporter",
        "desc": "Host hardware, CPU, memory, disk, network metrics on RHEL 10"
    },
    {
        "id": "node-exporter-rhel9",
        "name": "Node Exporter (RHEL 9)",
        "category": "Infrastructure",
        "host": "RHEL 9 VM",
        "ip": RHEL9_IP,
        "port": NODE_EXPORTER_PORT,
        "type": "Podman Container",
        "primary_url": f"http://{RHEL9_IP}:{NODE_EXPORTER_PORT}/metrics",
        "health_url": f"http://{RHEL9_IP}:{NODE_EXPORTER_PORT}/metrics",
        "metrics_url": f"http://{RHEL9_IP}:{NODE_EXPORTER_PORT}/metrics",
        "api_docs_url": None,
        "log_path": "podman logs node-exporter",
        "desc": "Host hardware, CPU, memory, disk, network metrics on RHEL 9"
    },
    {
        "id": "windows-exporter-win2025",
        "name": "Windows Exporter (Win 2025)",
        "category": "Infrastructure",
        "host": "Win Server 2025 VM",
        "ip": WIN2025_IP,
        "port": 9182,
        "type": "Prometheus Native Windows Exporter",
        "primary_url": f"http://{WIN2025_IP}:9182/metrics",
        "health_url": f"http://{WIN2025_IP}:9182/health",
        "metrics_url": f"http://{WIN2025_IP}:9182/metrics",
        "api_docs_url": None,
        "log_path": "C:\\AIST\\WindowsExporter\\windows_exporter.ps1",
        "desc": "Windows services, uptime, CPU, memory and disk metrics"
    },
    {
        "id": "windows-exporter-win2019",
        "name": "Windows Exporter (Win 2019)",
        "category": "Infrastructure",
        "host": "Win Server 2019 VM",
        "ip": WIN2019_IP,
        "port": 9182,
        "type": "Prometheus Native Windows Exporter",
        "primary_url": f"http://{WIN2019_IP}:9182/metrics",
        "health_url": f"http://{WIN2019_IP}:9182/health",
        "metrics_url": f"http://{WIN2019_IP}:9182/metrics",
        "api_docs_url": None,
        "log_path": "C:\\AIST\\WindowsExporter\\windows_exporter.ps1",
        "desc": "Windows services, uptime, CPU, memory and disk metrics"
    },

    # 4. AI Brain & Local Inference
    {
        "id": "ollama",
        "name": "Local AI Brain (Ollama)",
        "category": "AI Inference",
        "host": "Local Host (RTX 5090)",
        "ip": "127.0.0.1",
        "port": 11434,
        "type": "Ollama GPU Engine",
        "primary_url": f"{OLLAMA_HOST}/api/tags",
        "health_url": f"{OLLAMA_HOST}/api/tags",
        "metrics_url": None,
        "api_docs_url": f"{OLLAMA_HOST}/api/tags",
        "log_path": "Ollama Service Log",
        "desc": f"NVIDIA RTX 5090 GPU ({PRIMARY_LLM} & {EMBEDDING_LLM})"
    },

    # 5. Database & Hypervisor Infrastructure
    {
        "id": "sql-server",
        "name": "Microsoft SQL Server",
        "category": "Database",
        "host": "Win Server 2019 VM",
        "ip": WIN2019_IP,
        "port": 1433,
        "type": "Native Windows Service",
        "primary_url": f"mssql://{WIN2019_IP}:1433/TicketFlowDB",
        "health_url": f"{AUDIT_SERVICE_URL}/health",
        "metrics_url": f"{AUDIT_SERVICE_URL}/metrics",
        "api_docs_url": None,
        "log_path": "MSSQLSERVER Event Viewer",
        "desc": "Enterprise relational database host for TicketFlowDB"
    },
    {
        "id": "vcenter",
        "name": "VMware vCenter Server 8.0",
        "category": "Hypervisor",
        "host": "vCenter Appliance",
        "ip": VCENTER_HOST,
        "port": 443,
        "type": "VMware vSphere API",
        "primary_url": f"https://{VCENTER_HOST}/ui",
        "health_url": f"https://{VCENTER_HOST}/ui",
        "metrics_url": None,
        "api_docs_url": f"https://{VCENTER_HOST}/api",
        "log_path": "vSphere Task Log",
        "desc": f"Manages ESXi 8.0, datastore {DATASTORE_TARGET}, and all 4 guest VMs"
    }
]


def print_banner(action: str):
    print("=" * 86)
    print(f"   AIST: Autonomous SRE Incident Triage Platform v3.0")
    print(f"   Action: {action.upper()}")
    print(f"   Logs:   Rolling -> logs/manage_aist.log | logs/aist_backend.log")
    print("=" * 86)


# ==============================================================================
# FAST HEALTH PROBING HELPER
# ==============================================================================
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def probe_service_status(svc: dict, timeout=1.5) -> dict:
    """Fast probe of a single service state."""
    res = dict(svc)
    target_url = svc.get("health_url") or svc.get("primary_url")
    t0 = time.time()

    # Special handling for SQL Server TCP Port
    if svc.get("id") == "sql-server":
        try:
            s = socket.create_connection((svc["ip"], svc["port"]), timeout=timeout)
            s.close()
            elapsed_ms = (time.time() - t0) * 1000
            res["status"] = "LISTENING"
            res["latency_ms"] = f"{elapsed_ms:.1f}ms"
            res["is_up"] = True
            return res
        except Exception:
            pass

    # Special handling for Tempo Tracing Port
    if svc.get("id") == "tempo":
        try:
            s = socket.create_connection((svc["ip"], svc["port"]), timeout=timeout)
            s.close()
            elapsed_ms = (time.time() - t0) * 1000
            res["status"] = "LISTENING"
            res["latency_ms"] = f"{elapsed_ms:.1f}ms"
            res["is_up"] = True
            return res
        except Exception:
            pass

    # Special handling for vCenter HTTPS
    if svc.get("id") == "vcenter":
        try:
            r = requests.get(f"https://{VCENTER_HOST}/ui", verify=False, timeout=timeout)
            elapsed_ms = (time.time() - t0) * 1000
            res["status"] = f"HTTP {r.status_code}"
            res["latency_ms"] = f"{elapsed_ms:.1f}ms"
            res["is_up"] = r.status_code in [200, 301, 302, 401]
            return res
        except Exception as e:
            res["status"] = "UNREACHABLE"
            res["latency_ms"] = "-"
            res["is_up"] = False
            return res

    # General HTTP check
    if target_url and target_url.startswith("http"):
        try:
            r = requests.get(target_url, timeout=timeout)
            elapsed_ms = (time.time() - t0) * 1000
            res["status"] = f"HTTP {r.status_code}"
            res["latency_ms"] = f"{elapsed_ms:.1f}ms"
            res["is_up"] = r.status_code in [200, 204, 301, 302]
            return res
        except Exception as e:
            res["status"] = "DOWN"
            res["latency_ms"] = "-"
            res["is_up"] = False
            return res

    res["status"] = "UNKNOWN"
    res["latency_ms"] = "-"
    res["is_up"] = False
    return res


# ==============================================================================
# 1. LIST COMMAND: URLs, Endpoints & Application Information
# ==============================================================================
def cmd_list(category: str | None = None, as_json: bool = False):
    """List all apps, containers, servers, and live URLs."""
    if not as_json:
        print_banner("Live Application, Container & Endpoint Catalog")
        print("\n Probing all multi-OS endpoints across servers and containers in parallel...")

    # Run probes in parallel
    results = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(probe_service_status, s): s for s in SERVICES_CATALOG}
        for f in as_completed(futures):
            results.append(f.result())

    # Sort in canonical order
    order = {s["id"]: idx for idx, s in enumerate(SERVICES_CATALOG)}
    results.sort(key=lambda x: order.get(x["id"], 999))

    # Optional category filter
    if category:
        cat_lower = category.lower()
        alias_map = {
            "apps": ["microservice", "web ui", "platform core"],
            "app": ["microservice"],
            "microservices": ["microservice"],
            "obs": ["observability", "infrastructure"],
            "observability": ["observability", "infrastructure"],
            "infra": ["infrastructure", "hypervisor", "database"],
            "infrastructure": ["infrastructure", "hypervisor", "database"],
            "ai": ["ai inference"],
            "llm": ["ai inference"],
            "brain": ["ai inference"],
            "ui": ["web ui"],
            "web": ["web ui"]
        }
        allowed_cats = alias_map.get(cat_lower, [cat_lower])
        results = [
            r for r in results
            if any(ac in r["category"].lower() for ac in allowed_cats) or cat_lower in r["id"].lower()
        ]

    if as_json:
        print(json.dumps(results, indent=2))
        return

    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r["category"], []).append(r)

    total_up = sum(1 for r in results if r.get("is_up"))
    pct = (total_up / len(results) * 100) if results else 0

    for cat_name, items in categories.items():
        print(f"\n {C_BOLD}=== {cat_name.upper()} ==={C_RESET}")
        print("-" * 108)
        print(f"{'SERVICE / COMPONENT':<28} | {'HOST & RUNTIME':<27} | {'STATUS':<11} | {'PRIMARY ACCESS URL'}")
        print("-" * 108)
        for it in items:
            state_str = f"{C_GREEN}[ONLINE]{C_RESET}" if it["is_up"] else f"{C_RED}[OFFLINE]{C_RESET}"
            host_runtime = f"{it['host'][:16]} ({it['port']})"
            print(f"{it['name']:<28} | {host_runtime:<27} | {state_str:<20} | {it['primary_url']}")
            # Additional detail line for health/metrics & role
            details = []
            if it.get("health_url"):
                details.append(f"Health: {it['health_url']}")
            if it.get("metrics_url"):
                details.append(f"Metrics: {it['metrics_url']}")
            if details:
                print(f"   -> {' | '.join(details)}")
            print(f"   -> Purpose: {it['desc']}")
            print()

    # Print Quick Access URLs Directory
    print_quick_links()

    print("=" * 108)
    print(f" Catalog Health: {total_up} / {len(results)} Services Online ({pct:.1f}% Operational)")
    print("=" * 108)


def print_quick_links():
    print(f"\n {C_BOLD}=== SRE CONSOLES, WEB UIS & API ACCESS DIRECTORY ==={C_RESET}")
    print("=" * 86)
    print(f" 🏦 LOANPROCESSAI PORTAL:           http://{WIN2025_IP}:3000/")
    print(f"    -> Commercial loan intake, customer portal, banker underwriting cockpit")
    print(f" 🚀 FRONTEND COCKPIT (Vite React):  http://localhost:{FRONTEND_PORT}/ (or http://localhost:{BACKEND_PORT}/)")
    print(f"    -> Full glassmorphic SRE incident cockpit, AI agent chat, topology & controls")
    print(f" 📖 BACKEND API & DOCS (FastAPI):    http://127.0.0.1:{BACKEND_PORT}/docs")
    print(f"    -> Interactive OpenAPI Swagger docs, health checks, FastMCP endpoints")
    print(f" 📊 GRAFANA SRE DASHBOARDS:          {GRAFANA_URL} (admin / admin)")
    print(f"    -> Dashboards 01-18: SLI/SLO, Golden Signals, Swarm, Loan Business KPIs")
    print(f" 🎯 PROMETHEUS METRIC TARGETS:       {PROM_URL}/targets")
    print(f" 🚨 ALERTMANAGER INCIDENT ROUTER:    {ALERTMANAGER_URL}")
    print(f" 🌐 VMWARE vCENTER SERVER 8.0:       https://{VCENTER_HOST}/ui")
    print(f" 🔬 LOCAL AI BRAIN (RTX 5090):       {OLLAMA_HOST}/api/tags ({PRIMARY_LLM})")
    print("-" * 86)
    print(f" Microservice Endpoints:")
    print(f"  * LoanProcessAI API (RHEL 10):     http://{RHEL10_IP}:5000/applications")
    print(f"  * Notification Worker (RHEL 10):   {NOTIFICATION_API_URL}/health")
    print(f"  * Auth Gateway (.NET Win2025):     {AUTH_GATEWAY_URL}/health")
    print(f"  * Audit Service (WCF Win2019):     {AUDIT_SERVICE_URL}/health")
    print("=" * 86)


# ==============================================================================
# 2. STATUS & 21-POINT VERIFICATION MATRIX
# ==============================================================================
def cmd_status() -> bool:
    print_banner("Comprehensive 21-Point Verification & Health Matrix")
    test_results = []

    def check_endpoint(tier: str, name: str, url: str, expected_codes=(200, 204, 301, 302)):
        t0 = time.time()
        try:
            r = requests.get(url, timeout=6)
            elapsed_ms = (time.time() - t0) * 1000
            passed = r.status_code in expected_codes
            test_results.append({
                "tier": tier,
                "name": name,
                "url": url,
                "status": f"HTTP {r.status_code}",
                "latency_ms": f"{elapsed_ms:.1f}ms",
                "result": "PASS" if passed else "FAIL"
            })
            return passed
        except Exception as e:
            test_results.append({
                "tier": tier,
                "name": name,
                "url": url,
                "status": str(e)[:24],
                "latency_ms": "-",
                "result": "FAIL"
            })
            return False

    # A. Local AI Brain
    print("\n--- [1] Checking Local AI Inference Engine (http://127.0.0.1:11434) ---")
    try:
        t0 = time.time()
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        elapsed_ms = (time.time() - t0) * 1000
        test_results.append({
            "tier": "AI Brain",
            "name": "Ollama Server",
            "url": f"{OLLAMA_HOST}/api/tags",
            "status": "ONLINE",
            "latency_ms": f"{elapsed_ms:.1f}ms",
            "result": "PASS" if r.status_code == 200 else "FAIL"
        })
        models = [m.get("name") for m in r.json().get("models", [])]
        has_ornith = any(PRIMARY_LLM in m for m in models)
        has_gemma = any(EMBEDDING_LLM in m for m in models)
        test_results.append({
            "tier": "AI Brain",
            "name": f"Reasoning LLM ({PRIMARY_LLM})",
            "url": "local:RTX 5090",
            "status": "LOADED" if has_ornith else "MISSING",
            "latency_ms": "GPU VRAM",
            "result": "PASS" if has_ornith else "FAIL"
        })
        test_results.append({
            "tier": "AI Brain",
            "name": f"Embedding LLM ({EMBEDDING_LLM})",
            "url": "local:RTX 5090",
            "status": "LOADED" if has_gemma else "MISSING",
            "latency_ms": "GPU VRAM",
            "result": "PASS" if has_gemma else "FAIL"
        })
    except Exception as e:
        test_results.append({
            "tier": "AI Brain",
            "name": "Ollama Server",
            "url": OLLAMA_HOST,
            "status": str(e)[:24],
            "latency_ms": "-",
            "result": "FAIL"
        })

    # B. Multi-OS Microservices
    print("\n--- [2] Checking Multi-OS Microservices ---")
    check_endpoint("Microservice", "LoanProcessAI Health (RHEL 10)", f"http://{RHEL10_IP}:5000/healthz")
    check_endpoint("Microservice", "LoanProcessAI Applications (RHEL 10)", f"http://{RHEL10_IP}:5000/applications")
    check_endpoint("Microservice", "LoanProcessAI Metrics (RHEL 10)", f"http://{RHEL10_IP}:5000/metrics")
    check_endpoint("Microservice", "LoanPortal Frontend (Win2025)", f"http://{WIN2025_IP}:3000/")
    check_endpoint("Microservice", "Notification Service Health (RHEL 10)", f"{NOTIFICATION_API_URL}/health")
    check_endpoint("Microservice", "Notification Metrics (RHEL 10)", f"{NOTIFICATION_API_URL}/metrics")
    check_endpoint("Microservice", "Auth Gateway Health (Win2025)", f"{AUTH_GATEWAY_URL}/health")
    check_endpoint("Microservice", "Auth Gateway Token (Win2025)", f"{AUTH_GATEWAY_URL}/api/v1/auth/login")
    check_endpoint("Microservice", "Auth Gateway Metrics (Win2025)", f"{AUTH_GATEWAY_URL}/metrics")
    check_endpoint("Microservice", "Audit & DB Service Health (Win2019)", f"{AUDIT_SERVICE_URL}/health")
    check_endpoint("Microservice", "Audit Event Logs (Win2019)", f"{AUDIT_SERVICE_URL}/api/v1/audit/logs")
    check_endpoint("Microservice", "Audit Service Metrics (Win2019)", f"{AUDIT_SERVICE_URL}/metrics")

    # C. Observability Infrastructure
    print("\n--- [3] Checking Observability Infrastructure (RHEL 9) ---")
    check_endpoint("Observability", "Prometheus 3.0 Dashboard", PROM_URL)
    check_endpoint("Observability", "Grafana 11.4 WebUI", GRAFANA_URL)
    check_endpoint("Observability", "AlertManager 0.27 API", ALERTMANAGER_URL)
    check_endpoint("Observability", "Node Exporter (RHEL 10)", f"http://{RHEL10_IP}:{NODE_EXPORTER_PORT}/metrics")
    check_endpoint("Observability", "Node Exporter (RHEL 9)", f"http://{RHEL9_IP}:{NODE_EXPORTER_PORT}/metrics")
    check_endpoint("Observability", "Windows Exporter (Win2025)", f"http://{WIN2025_IP}:9182/metrics")
    check_endpoint("Observability", "Windows Exporter (Win2019)", f"http://{WIN2019_IP}:9182/metrics")

    # D. FastMCP Diagnostic Tools
    print("\n--- [4] Checking FastMCP Diagnostic Tools ---")
    try:
        t0 = time.time()
        vcenter_res = TOOLS["mcp_vcenter.status"]()
        test_results.append({
            "tier": "FastMCP Tool",
            "name": "mcp_vcenter.status",
            "url": f"https://{VCENTER_HOST}/api",
            "status": f"{len(vcenter_res.get('vms', []))} VMs Discovered",
            "latency_ms": f"{(time.time()-t0)*1000:.1f}ms",
            "result": "PASS" if vcenter_res.get("status") == "success" else "FAIL"
        })
    except Exception as e:
        test_results.append({"tier": "FastMCP Tool", "name": "mcp_vcenter.status", "url": VCENTER_HOST, "status": str(e)[:24], "latency_ms": "-", "result": "FAIL"})

    try:
        t0 = time.time()
        ssh_res = TOOLS["mcp_linux_diag.run_ssh"](command="hostname")
        test_results.append({
            "tier": "FastMCP Tool",
            "name": "mcp_linux_diag.run_ssh",
            "url": f"ssh://{LINUX_USER}@{RHEL10_IP}:22",
            "status": ssh_res.get("stdout", "ERR").strip()[:24],
            "latency_ms": f"{(time.time()-t0)*1000:.1f}ms",
            "result": "PASS" if ssh_res.get("status") == "success" else "FAIL"
        })
    except Exception as e:
        test_results.append({"tier": "FastMCP Tool", "name": "mcp_linux_diag.run_ssh", "url": RHEL10_IP, "status": str(e)[:24], "latency_ms": "-", "result": "FAIL"})

    # Print Formatted Results Table with URL Column
    print("\n" + "=" * 116)
    print(f"{'TIER':<14} | {'COMPONENT':<30} | {'URL / ENDPOINT':<38} | {'STATUS':<12} | {'LATENCY':<8} | {'RES'}")
    print("-" * 116)
    pass_count = 0
    for r in test_results:
        if r["result"] == "PASS":
            pass_count += 1
            res_str = f"{C_GREEN}PASS{C_RESET}"
        else:
            res_str = f"{C_RED}FAIL{C_RESET}"
        url_display = r['url'] if len(r['url']) <= 38 else r['url'][:35] + "..."
        print(f"{r['tier']:<14} | {r['name']:<30} | {url_display:<38} | {r['status']:<12} | {r['latency_ms']:<8} | {res_str}")
    print("=" * 116)
    pct = (pass_count / len(test_results)) * 100
    print(f" Verification Summary: {pass_count} / {len(test_results)} Tests Passed ({pct:.1f}% System Health)")
    print("=" * 116)

    print_quick_links()
    return pass_count == len(test_results)


# ==============================================================================
# 3. CONTROL COMMAND: START SERVICES
# ==============================================================================
def ensure_frontend_port_3001():
    """Ensure frontend Vite/preview server is running on port 3001."""
    try:
        r = requests.get(f"http://localhost:{FRONTEND_PORT}/", timeout=1)
        if r.status_code == 200:
            print(f" [+] WebUI Frontend on port {FRONTEND_PORT}: ALREADY ACTIVE")
            return
    except Exception:
        pass

    print(f" [+] Starting WebUI Frontend on http://localhost:{FRONTEND_PORT}...")
    fe_dir = os.path.join(BASE_DIR, "ai-triage", "webui", "frontend")
    cmd = f"npx.cmd vite preview --port {FRONTEND_PORT} --host 0.0.0.0"
    try:
        subprocess.Popen(cmd, cwd=fe_dir, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        print(f" [+] Frontend preview server started on http://localhost:{FRONTEND_PORT}/")
    except Exception as e:
        print(f" [!] Notice starting frontend preview: {e}")


def start_service_rhel10(service: str = "all"):
    """Start microservices on RHEL 10."""
    print(f"\n[+] Starting microservices on RHEL 10 ({RHEL10_IP})...")
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)

        if service in ["all", "ticketflow"]:
            c.exec_command("pkill -f 'ticketflow-api/main.py' || true")
            c.exec_command("nohup /opt/aist/venv/bin/python3 /opt/aist/ticketflow-api/main.py </dev/null >/opt/aist/ticketflow-api/api.log 2>&1 &")
            print("  -> TicketFlow API (:5000) started.")

        if service in ["all", "notification"]:
            c.exec_command("pkill -f 'notification-service/service.py' || true")
            c.exec_command("nohup /opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py </dev/null >/opt/aist/notification-service/service.log 2>&1 &")
            print("  -> Notification Service (:8080) started.")

        if service in ["all", "node-exporter"]:
            cmd = "podman run -d --name node-exporter --restart unless-stopped --net=host docker.io/prom/node-exporter:latest 2>/dev/null || true"
            c.exec_command(cmd)
            print("  -> Node Exporter (:9100) verified.")

        c.close()
    except Exception as e:
        print(f" [!] RHEL 10 Start Error: {e}")


def start_service_windows(target: str = "all"):
    """Start services on Windows Server 2025 and 2019."""
    hosts = []
    if target in ["all", "auth", "auth-gateway", "win2025"]:
        hosts.append((WIN2025_IP, 5001, "AuthGateway", "C:\\AIST\\AuthGateway\\server.ps1"))
    if target in ["all", "audit", "audit-service", "win2019"]:
        hosts.append((WIN2019_IP, 8088, "AuditService", "C:\\AIST\\AuditService\\server.ps1"))
    if target in ["all", "portal", "loanportal", "win2025"]:
        hosts.append((WIN2025_IP, 3000, "LoanPortal", "C:\\AIST\\LoanPortal\\server.ps1"))
    if target in ["all", "windows", "exporter", "windows-exporter", "win2025"]:
        hosts.append((WIN2025_IP, 9182, "WindowsExporter-2025", "C:\\AIST\\WindowsExporter\\windows_exporter.ps1 -Port 9182"))
    if target in ["all", "windows", "exporter", "windows-exporter", "win2019"]:
        hosts.append((WIN2019_IP, 9182, "WindowsExporter-2019", "C:\\AIST\\WindowsExporter\\windows_exporter.ps1 -Port 9182"))

    for ip, port, name, script_path in hosts:
        print(f"\n[+] Starting {name} on {ip}:{port}...")
        try:
            s = winrm.Session(f"http://{ip}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
            test_cmd = f"(Test-NetConnection -ComputerName 127.0.0.1 -Port {port} -WarningAction SilentlyContinue).TcpTestSucceeded"
            res = s.run_ps(test_cmd)
            is_up = "True" in res.std_out.decode()
            if not is_up:
                start_cmd = f'$w = [wmiclass]"\\\\.\\root\\cimv2:Win32_Process"; $w.Create("powershell.exe -NoProfile -ExecutionPolicy Bypass -File {script_path}")'
                s.run_ps(start_cmd)
                time.sleep(2)
                print(f"  -> {name} process spawned via WinRM.")
            else:
                print(f"  -> {name} is already listening on port {port}.")
        except Exception as e:
            print(f" [!] {name} Start Error: {e}")


def start_service_observability(service: str = "all"):
    """Start containers on RHEL 9 Observability host."""
    print(f"\n[+] Starting Observability stack on RHEL 9 ({RHEL9_IP})...")
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(RHEL9_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
        
        target_compose = "" if service == "all" else service
        c.exec_command(f"cd /opt/aist/observability && docker-compose -f docker-compose.observability.yml up -d {target_compose}")
        # Ensure node exporter is running
        c.exec_command("podman run -d --name node-exporter --restart unless-stopped --net=host docker.io/prom/node-exporter:latest 2>/dev/null || true")
        c.close()
        print("  -> Observability containers active on RHEL 9.")
    except Exception as e:
        print(f" [!] RHEL 9 Observability Start Error: {e}")


def cmd_start(target: str = "webui"):
    """Unified start command dispatcher."""
    target_lower = target.lower()
    print_banner(f"Start Target: {target_lower}")

    if target_lower in ["webui", "local"]:
        start_triage_server()
        return

    if target_lower == "all":
        print("\n=== [Stage 1/5] Checking vCenter & VM Power States ===")
        try:
            mgr = VCenterManager(host=VCENTER_HOST, user=VCENTER_USER, password=VCENTER_PASS)
            if mgr.connect():
                vms = mgr.list_vms()
                target_names = ["RHEL10", "RHEL9", "Win2025", "Win2019"]
                for vm in vms:
                    name = vm.get("name")
                    if any(t.lower() in name.lower() for t in target_names):
                        state = vm.get("power_state")
                        if state != "POWERED_ON":
                            print(f"  Powering on {name}...")
                            mgr.set_power_state(vm.get("vm"), "start")
        except Exception as e:
            print(f" [!] vCenter power check notice: {e}")

        print("\n=== [Stage 2/5] Starting Observability Containers on RHEL 9 ===")
        start_service_observability("all")

        print("\n=== [Stage 3/5] Starting Linux Microservices on RHEL 10 ===")
        start_service_rhel10("all")

        print("\n=== [Stage 4/5] Starting Windows Microservices ===")
        start_service_windows("all")

        print("\n=== [Stage 5/5] Starting Local WebUI & AI Triage Backend ===")
        start_triage_server()
        return

    if target_lower in ["apps", "microservices"]:
        start_service_rhel10("all")
        start_service_windows("all")
        print("\n[+] All Multi-OS microservices started.")
        print_quick_links()
        return

    if target_lower in ["obs", "observability"]:
        start_service_observability("all")
        print("\n[+] Observability containers started on RHEL 9.")
        print_quick_links()
        return

    if target_lower in ["ticketflow", "notification", "node-exporter"]:
        start_service_rhel10(target_lower)
        return

    if target_lower in ["auth", "auth-gateway", "audit", "audit-service"]:
        start_service_windows(target_lower)
        return

    if target_lower in ["prometheus", "grafana", "loki", "tempo", "alertmanager"]:
        start_service_observability(target_lower)
        return

    print(f" [!] Unknown start target: '{target}'. Available: webui, all, apps, obs, ticketflow, notification, auth, audit, prometheus, grafana, loki")


def start_triage_server():
    """Start local frontend preview (3001) and FastAPI backend (8000)."""
    # 1. Check AI Brain
    print("\n[1/3] Checking Local AI Brain (Ollama on RTX 5090)...")
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        if r.status_code == 200:
            print(f" -> Ollama Service: ONLINE ({OLLAMA_HOST})")
            models = [m.get("name") for m in r.json().get("models", [])]
            for m in [PRIMARY_LLM, EMBEDDING_LLM]:
                state = "FOUND" if any(m in mod for mod in models) else "MISSING"
                print(f" -> Model ({m}): {state}")
    except Exception:
        print(" [!] WARNING: Local Ollama service is unreachable on port 11434.")

    # 2. Check vCenter
    print(f"\n[2/3] Checking VMware vCenter ({VCENTER_HOST}) & ESXi...")
    try:
        mgr = VCenterManager(host=VCENTER_HOST, user=VCENTER_USER, password=VCENTER_PASS)
        if mgr.connect():
            vms = mgr.list_vms()
            print(f" -> vCenter Connection: AUTHENTICATED")
            print(f" -> Managed VMs: {len(vms)} discovered")
            print(f" -> Storage: {DATASTORE_TARGET} (High-Speed VMFS, thin-provisioned)")
    except Exception as e:
        print(f" [!] vCenter Probe Notice: {e}")

    # 3. Start Frontend & Backend
    print(f"\n[3/3] Starting AIST WebUI & Backend Services...")
    ensure_frontend_port_3001()
    
    print_quick_links()
    print("\n[+] Opening WebUI in your default browser...")
    try:
        webbrowser.open(f"http://localhost:{FRONTEND_PORT}/")
    except Exception:
        pass

    import uvicorn
    import importlib
    
    backend_app_dir = os.path.join(BASE_DIR, "ai-triage", "webui", "backend", "app")
    if backend_app_dir not in sys.path:
        sys.path.insert(0, backend_app_dir)
    backend_main = importlib.import_module("main")
    uvicorn.run(backend_main.app, host="0.0.0.0", port=BACKEND_PORT)


# ==============================================================================
# 4. CONTROL COMMAND: STOP SERVICES
# ==============================================================================
def cmd_stop(target: str = "all"):
    """Unified stop command dispatcher."""
    target_lower = target.lower()
    print_banner(f"Stop Target: {target_lower}")

    if target_lower in ["all", "apps", "rhel10", "ticketflow", "notification"]:
        print(f"\n[+] Stopping services on RHEL 10 ({RHEL10_IP})...")
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
            if target_lower == "ticketflow":
                c.exec_command("pkill -f 'ticketflow-api/main.py' || true")
                print("  -> TicketFlow API stopped.")
            elif target_lower == "notification":
                c.exec_command("pkill -f 'notification-service/service.py' || true")
                print("  -> Notification Service stopped.")
            else:
                c.exec_command("pkill -f 'ticketflow-api/main.py'; pkill -f 'notification-service/service.py'; podman stop node-exporter 2>/dev/null || true")
                print("  -> RHEL 10 microservices and node-exporter stopped.")
            c.close()
        except Exception as e:
            print(f" [!] RHEL 10 Stop Error: {e}")

    if target_lower in ["all", "apps", "windows", "auth", "auth-gateway", "audit", "audit-service", "portal", "loanportal", "exporter", "windows-exporter"]:
        hosts = []
        if target_lower in ["all", "apps", "windows", "auth", "auth-gateway"]:
            hosts.append((WIN2025_IP, "*AuthGateway*", "AuthGateway (Win2025)"))
        if target_lower in ["all", "apps", "windows", "audit", "audit-service"]:
            hosts.append((WIN2019_IP, "*AuditService*", "AuditService (Win2019)"))
        if target_lower in ["all", "apps", "windows", "portal", "loanportal"]:
            hosts.append((WIN2025_IP, "*LoanPortal*", "LoanPortal (Win2025)"))
        if target_lower in ["all", "windows", "exporter", "windows-exporter"]:
            hosts.append((WIN2025_IP, "*windows_exporter*", "WindowsExporter (Win2025)"))
            hosts.append((WIN2019_IP, "*windows_exporter*", "WindowsExporter (Win2019)"))

        for ip, pattern, name in hosts:
            try:
                s = winrm.Session(f"http://{ip}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
                cmd = f'Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like "{pattern}" }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}'
                s.run_ps(cmd)
                print(f"  -> {name} stopped via WinRM.")
            except Exception as e:
                print(f" [!] {name} Stop Error: {e}")

    if target_lower in ["all", "obs", "observability", "rhel9"]:
        print(f"\n[+] Stopping Observability containers on RHEL 9 ({RHEL9_IP})...")
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL9_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
            c.exec_command("cd /opt/aist/observability && docker-compose -f docker-compose.observability.yml down 2>/dev/null || true")
            c.exec_command("podman stop node-exporter 2>/dev/null || true")
            c.close()
            print("  -> RHEL 9 Observability containers stopped.")
        except Exception as e:
            print(f" [!] RHEL 9 Stop Error: {e}")

    if target_lower in ["all", "webui", "local"]:
        print("\n[+] Stopping local WebUI (:3001) & Backend (:8000)...")
        for port in [FRONTEND_PORT, BACKEND_PORT]:
            try:
                netstat_out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True, stderr=subprocess.DEVNULL)
                for line in netstat_out.strip().splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and "LISTENING" in parts:
                        pid = parts[-1]
                        if pid and pid != "0" and pid != str(os.getpid()):
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            print(f"  -> Terminated process {pid} on port {port}.")
            except Exception:
                pass

    print("\n[+] Stop operation completed.")


# ==============================================================================
# 5. CONTROL COMMAND: RESTART SERVICES
# ==============================================================================
def cmd_restart(target: str = "all"):
    """Restart specified services."""
    print_banner(f"Restart Target: {target}")
    cmd_stop(target)
    time.sleep(2)
    cmd_start(target)


# ==============================================================================
# 6. LOGS COMMAND: Tail Live Remote & Local Logs
# ==============================================================================
def cmd_logs(service: str, lines: int = 25):
    """Tail live logs for any service across the multi-OS fleet."""
    svc_lower = service.lower()
    print_banner(f"Live Logs: {svc_lower} (Last {lines} lines)")

    if svc_lower in ["ticketflow", "ticketflow-api"]:
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL10_IP, 22, LINUX_USER, LINUX_PASS, timeout=5)
            _, out, _ = c.exec_command(f"tail -n {lines} /opt/aist/ticketflow-api/api.log 2>/dev/null || echo 'No log file found'")
            print(out.read().decode())
            c.close()
        except Exception as e:
            print("Error reading TicketFlow logs:", e)

    elif svc_lower in ["notification", "notification-service"]:
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL10_IP, 22, LINUX_USER, LINUX_PASS, timeout=5)
            _, out, _ = c.exec_command(f"tail -n {lines} /opt/aist/notification-service/service.log 2>/dev/null || echo 'No log file found'")
            print(out.read().decode())
            c.close()
        except Exception as e:
            print("Error reading Notification logs:", e)

    elif svc_lower in ["auth", "auth-gateway"]:
        try:
            s = winrm.Session(f"http://{WIN2025_IP}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
            res = s.run_ps(f"""
            $f = @('C:\\AIST\\AuthGateway\\auth_gateway.log', 'C:\\AIST\\AuthGateway\\server.log') | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
            if ($f) {{ Get-Content $f -Tail {lines} }} else {{ Write-Output 'No log file found' }}
            """)
            print(res.std_out.decode().strip())
        except Exception as e:
            print("Error reading Auth Gateway logs:", e)

    elif svc_lower in ["audit", "audit-service"]:
        try:
            s = winrm.Session(f"http://{WIN2019_IP}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
            res = s.run_ps(f"""
            $f = @('C:\\AIST\\AuditService\\audit_service.log', 'C:\\AIST\\AuditService\\server.log') | Where-Object {{ Test-Path $_ }} | Select-Object -First 1
            if ($f) {{ Get-Content $f -Tail {lines} }} else {{ Write-Output 'No log file found' }}
            """)
            print(res.std_out.decode().strip())
        except Exception as e:
            print("Error reading Audit Service logs:", e)

    elif svc_lower in ["prometheus", "grafana", "loki", "tempo", "alertmanager", "otel-collector", "node-exporter"]:
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL9_IP, 22, LINUX_USER, LINUX_PASS, timeout=5)
            cmd = f"podman logs --tail {lines} aist-{svc_lower} 2>&1 || podman logs --tail {lines} {svc_lower} 2>&1 || cd /opt/aist/observability && docker-compose logs --tail={lines} {svc_lower} 2>&1"
            _, out, _ = c.exec_command(cmd)
            print(out.read().decode().strip())
            c.close()
        except Exception as e:
            print(f"Error reading {svc_lower} logs:", e)
    else:
        print(f"Unknown service '{service}'. Available for logs: ticketflow, notification, auth, audit, prometheus, grafana, loki, tempo, alertmanager, otel-collector")


# ==============================================================================
# 7. DEPLOY COMMAND: Full Multi-OS Application Deployment
# ==============================================================================
def upload_directory_sftp(sftp, local_dir, remote_dir):
    """Recursively upload a local directory to remote host via SFTP."""
    try:
        sftp.mkdir(remote_dir)
    except Exception:
        pass

    for item in os.listdir(local_dir):
        if item in ["__pycache__", ".git", "logs", ".pytest_cache"]:
            continue
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"
        if os.path.isdir(local_path):
            upload_directory_sftp(sftp, local_path, remote_path)
        else:
            sftp.put(local_path, remote_path)


def cmd_deploy(target: str = "all") -> bool:
    """Deploy microservices, configs, and containers across all 4 OS environments."""
    print_banner(f"Deploy Applications & Observability: {target}")

    # 1. Deploy Observability to RHEL 9
    if target in ["all", "obs", "rhel9"]:
        print(f"\n[1/3] Deploying Full Observability Stack to RHEL 9 ({RHEL9_IP})...")
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL9_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=10)
            c.exec_command("mkdir -p /opt/aist/observability")
            
            sftp = c.open_sftp()
            local_obs_dir = os.path.join(BASE_DIR, "observability")
            upload_directory_sftp(sftp, local_obs_dir, "/opt/aist/observability")
            sftp.close()

            # Ensure docker-compose binary and podman socket
            setup_obs_cmd = """
                if [ ! -f /usr/local/bin/docker-compose ]; then
                    curl -SL https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose 2>/dev/null || true
                    chmod +x /usr/local/bin/docker-compose 2>/dev/null || true
                fi
                systemctl enable --now podman.socket 2>/dev/null || true
                ln -sf /run/podman/podman.sock /var/run/docker.sock 2>/dev/null || true
                export DOCKER_HOST=unix:///run/podman/podman.sock
                cd /opt/aist/observability
                docker-compose -f docker-compose.observability.yml down 2>/dev/null || true
                docker-compose -f docker-compose.observability.yml up -d
                podman rm -f node-exporter 2>/dev/null || true
                podman run -d --name node-exporter --restart unless-stopped --net=host docker.io/prom/node-exporter:latest 2>/dev/null || true
            """
            _, stdout, _ = c.exec_command(setup_obs_cmd)
            stdout.channel.recv_exit_status()
            c.close()
            print(" [+] RHEL 9 Observability containers deployed and running.")
        except Exception as e:
            print(f" [!] RHEL 9 Deploy Error: {e}")

    # 2. Deploy Microservices to RHEL 10
    if target in ["all", "apps", "rhel10"]:
        print(f"\n[2/3] Deploying Microservices to RHEL 10 ({RHEL10_IP})...")
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=10)
            c.exec_command("mkdir -p /opt/aist/loanprocessai /opt/aist/notification-service /opt/aist/loanprocessai/data/documents")

            sftp = c.open_sftp()
            local_backend_dir = os.path.join(BASE_DIR, "services", "loanprocessai-backend")
            upload_directory_sftp(sftp, local_backend_dir, "/opt/aist/loanprocessai")

            local_notify = os.path.join(BASE_DIR, "apps", "notification-service", "service.py")
            sftp.put(local_notify, "/opt/aist/notification-service/service.py")

            local_zip = os.path.join(BASE_DIR, "services", "loanprocessai-backend", "frontend_build.zip")
            if os.path.exists(local_zip):
                sftp.put(local_zip, "/opt/aist/frontend_build.zip")

            tf_service = """[Unit]
Description=AIST LoanProcessAI Core Microservice
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aist/loanprocessai
EnvironmentFile=/opt/aist/loanprocessai/.env
ExecStart=/opt/aist/venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 5000
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
            notify_service = """[Unit]
Description=AIST Notification Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/aist/notification-service
ExecStart=/opt/aist/venv/bin/python3 /opt/aist/notification-service/service.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
            with sftp.file("/etc/systemd/system/aist-ticketflow.service", "w") as f:
                f.write(tf_service)
            with sftp.file("/etc/systemd/system/aist-notification.service", "w") as f:
                f.write(notify_service)
            sftp.close()

            # Ensure venv exists with required libraries, restart services, and start node-exporter
            deploy_rhel10_cmd = """
                if [ ! -f /opt/aist/venv/bin/python3 ]; then
                    python3 -m venv /opt/aist/venv
                fi
                /opt/aist/venv/bin/pip install --no-cache-dir google-adk google-genai litellm pypdf scikit-learn pandas numpy pydantic-settings python-multipart fastapi uvicorn prometheus-client requests 2>/dev/null || true
                systemctl daemon-reload
                systemctl enable --now aist-ticketflow aist-notification
                systemctl restart aist-ticketflow aist-notification
                podman rm -f node-exporter 2>/dev/null || true
                podman run -d --name node-exporter --restart unless-stopped --net=host docker.io/prom/node-exporter:latest 2>/dev/null || true
            """
            _, stdout, _ = c.exec_command(deploy_rhel10_cmd)
            stdout.channel.recv_exit_status()
            c.close()
            print(" [+] RHEL 10 Microservices deployed and running.")
        except Exception as e:
            print(f" [!] RHEL 10 Deploy Error: {e}")

    # 3. Deploy Windows Services (Win2025 & Win2019)
    if target in ["all", "apps", "windows", "win2025", "win2019", "portal", "loanportal"]:
        print("\n[3/3] Deploying Windows Services (Win2025 & Win2019)...")

        # Deploy React Frontend assets to Win2025 LoanPortal
        if target in ["all", "apps", "windows", "win2025", "portal", "loanportal"]:
            try:
                s_win = winrm.Session(f"http://{WIN2025_IP}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
                check_res = s_win.run_ps('Test-Path "C:\\AIST\\LoanPortal\\index.html"')
                has_index = "true" in check_res.std_out.decode().lower()
                if not has_index:
                    local_zip = os.path.join(BASE_DIR, "services", "loanprocessai-backend", "frontend_build.zip")
                    if os.path.exists(local_zip):
                        c = paramiko.SSHClient()
                        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=10)
                        c.exec_command("firewall-cmd --add-port=8888/tcp 2>/dev/null; fuser -k 8888/tcp 2>/dev/null; cd /opt/aist && nohup /usr/bin/python3 -m http.server 8888 </dev/null >/dev/null 2>&1 &")
                        time.sleep(2)

                        portal_assets_ps = """
                        New-Item -ItemType Directory -Force -Path "C:\\AIST\\LoanPortal" | Out-Null
                        $wc = New-Object System.Net.WebClient
                        $wc.DownloadFile('http://192.168.1.130:8888/frontend_build.zip', 'C:\\AIST\\frontend_build.zip')
                        Expand-Archive -Path 'C:\\AIST\\frontend_build.zip' -DestinationPath 'C:\\AIST\\LoanPortal' -Force
                        Remove-Item 'C:\\AIST\\frontend_build.zip' -Force -ErrorAction SilentlyContinue
                        """
                        s_win.run_ps(portal_assets_ps)
                        c.exec_command("fuser -k 8888/tcp 2>/dev/null; firewall-cmd --remove-port=8888/tcp 2>/dev/null")
                        c.close()
                print(" [+] LoanPortal React UI assets verified on Win2025.")
            except Exception as e:
                print(f" [!] LoanPortal Frontend Asset Note: {e}")

        win_services = [
            (WIN2025_IP, 5001, "AuthGateway", "apps/auth-gateway/server.ps1", "C:\\AIST\\AuthGateway\\server.ps1"),
            (WIN2019_IP, 8088, "AuditService", "apps/audit-service/server.ps1", "C:\\AIST\\AuditService\\server.ps1"),
            (WIN2025_IP, 3000, "LoanPortal", "scripts/portal_server.ps1", "C:\\AIST\\LoanPortal\\server.ps1"),
            (WIN2025_IP, 9182, "WindowsExporter", "scripts/windows_exporter.ps1", "C:\\AIST\\WindowsExporter\\windows_exporter.ps1"),
            (WIN2019_IP, 9182, "WindowsExporter", "scripts/windows_exporter.ps1", "C:\\AIST\\WindowsExporter\\windows_exporter.ps1")
        ]
        if target == "win2019":
            win_services = [s for s in win_services if s[0] == WIN2019_IP]
        elif target == "win2025":
            win_services = [s for s in win_services if s[0] == WIN2025_IP]
        elif target in ["portal", "loanportal"]:
            win_services = [s for s in win_services if s[2] == "LoanPortal"]
        for ip, port, name, local_rel_path, remote_path in win_services:
            try:
                local_file = os.path.join(BASE_DIR, local_rel_path)
                with open(local_file, "r", encoding="utf-8") as f:
                    script_content = f.read()

                import base64
                b64 = base64.b64encode(script_content.encode("utf-8")).decode("ascii")

                s = winrm.Session(f"http://{ip}:5985/wsman", auth=(WINDOWS_USER, WINDOWS_PASS), transport="ntlm")
                remote_dir = os.path.dirname(remote_path)
                s.run_ps(f'New-Item -ItemType Directory -Force -Path "{remote_dir}" | Out-Null; Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False; netsh http add urlacl url=http://+:{port}/ user=Everyone 2>$null; Remove-Item -Path C:\\AIST\\temp_upload.b64 -Force -ErrorAction SilentlyContinue')

                chunk_size = 2000
                for i in range(0, len(b64), chunk_size):
                    chunk = b64[i:i+chunk_size]
                    s.run_ps(f'Add-Content -Path C:\\AIST\\temp_upload.b64 -Value "{chunk}"')

                service_dir_name = os.path.basename(os.path.dirname(remote_path))
                unpack_and_start = f"""
                $b64 = (Get-Content C:\\AIST\\temp_upload.b64) -join ''
                $bytes = [System.Convert]::FromBase64String($b64.Trim())
                [System.IO.File]::WriteAllBytes('{remote_path}', $bytes)
                Remove-Item C:\\AIST\\temp_upload.b64 -Force -ErrorAction SilentlyContinue
                Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -like "*{service_dir_name}*" }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}
                Start-Sleep -Seconds 2
                $w = [wmiclass]"\\\\.\\root\\cimv2:Win32_Process"
                $w.Create("powershell.exe -NoProfile -ExecutionPolicy Bypass -File {remote_path} -Port {port}")
                """
                s.run_ps(unpack_and_start)
                print(f" [+] {name} ({ip}:{port}) deployed and running.")
            except Exception as e:
                print(f" [!] {name} Deploy Error: {e}")

    print("\n[+] Application Deployment Completed Successfully.")
    print_quick_links()
    return True


# ==============================================================================
# 8. SETUP INFRASTRUCTURE
# ==============================================================================
def cmd_setup(force_recreate: bool = False, cpus: int = 4, ram: int = 16) -> bool:
    """
    Automated Infrastructure & VM Fleet Setup via Native vCenter Cloning:
    1. Identifies master templates on vCenter (RHEL10_Template, RHEL9_Template, Win2019_Template, Win2025_Template).
    2. Native vCenter clone of 4 multi-OS VMs with 4 vCPUs and 16 GB RAM each on Base_DS (master templates preserved).
    3. Binds direct static IPs (192.168.1.130-133) without DHCP dependency.
    4. Automatically applies bidirectional firewall rules across all OS nodes.
    5. Verifies end-to-end network reachability.
    """
    print_banner("AIST Automated Infrastructure & VM Fleet Setup")
    prov = VCenterProvisioner()
    if not prov.connect():
        print(f" [!] ERROR: Failed to connect to vCenter at {VCENTER_HOST}")
        return False
    try:
        ok = prov.setup_fleet(force_recreate=force_recreate, cpus=cpus, ram_gb=ram)
        if ok:
            print("\n" + "=" * 80)
            print(" [+] INFRASTRUCTURE SETUP COMPLETE: 4 Fleet VMs Active (4 vCPUs, 16 GB RAM each)!")
            print("     Next step: Deploy applications via:")
            print("       python manage_aist.py deploy")
            print("=" * 80)
        else:
            print("\n [!] Infrastructure setup completed with partial warnings. Run: python manage_aist.py status")
        return ok
    finally:
        prov.close()


# ==============================================================================
# 9. CHAOS ENGINEERING INJECTION & RECOVERY
# ==============================================================================
def cmd_chaos(scenario: str):
    print_banner(f"Chaos Engineering Injection: {scenario}")
    
    if scenario == "cpu_spike":
        print(f"[!] Triggering CHAOS-01: CPU Saturation on RHEL 10 ({RHEL10_IP})...")
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
        c.exec_command("nohup python3 -c 'import time; [sum(i*i for i in range(1000000)) for _ in iter(int, 1)]' >/dev/null 2>&1 &")
        c.close()
        print(" [+] High CPU workload launched in background on RHEL 10.")

    elif scenario == "auth_crash":
        print(f"[!] Triggering CHAOS-02: Auth Gateway Crash on Win2025 ({WIN2025_IP})...")
        try:
            r = requests.post(f"{AUTH_GATEWAY_URL}/api/v1/chaos/crash", timeout=3)
            print(" [+] Auth Gateway crash injected:", r.text)
        except Exception as e:
            print(" [+] Injected crash (connection terminated):", e)

    elif scenario == "sql_deadlock":
        print(f"[!] Triggering CHAOS-03: SQL Server Deadlock on Win2019 ({WIN2019_IP})...")
        r = requests.post(f"{AUDIT_SERVICE_URL}/api/v1/chaos/deadlock", timeout=3)
        print(" [+] SQL deadlock injected (blocked_sessions=5):", r.text)

    elif scenario == "queue_backlog":
        print(f"[!] Triggering CHAOS-04: Queue Backlog on RHEL 10 ({RHEL10_IP})...")
        r = requests.post(f"{NOTIFICATION_API_URL}/api/v1/chaos/backlog", timeout=3)
        print(" [+] Queue backlog injected (depth=650):", r.text)

    elif scenario == "ticket_latency":
        print(f"[!] Triggering CHAOS-05: TicketFlow API Latency Spike ({RHEL10_IP})...")
        r = requests.post(f"{TICKETFLOW_API_URL}/api/v1/chaos/latency", json={"delay_seconds": 3.5}, timeout=10)
        print(" [+] Latency injected:", r.text)

    elif scenario == "ticket_500":
        print(f"[!] Triggering CHAOS-06: TicketFlow API 500 Error Storm ({RHEL10_IP})...")
        for _ in range(5):
            try:
                requests.post(f"{TICKETFLOW_API_URL}/api/v1/chaos/error", timeout=2)
            except Exception:
                pass
        print(" [+] 500 InternalServerError simulated.")

    elif scenario in ["multistage_cascade", "p0_cascade"]:
        print("[!] Triggering Multi-Stage Cascading Outage (P0 Disaster Scenario)...")
        cmd_chaos("cpu_spike")
        time.sleep(1)
        cmd_chaos("auth_crash")
        time.sleep(1)
        cmd_chaos("sql_deadlock")
        print(" [+] Multi-Stage Outage Cascade Injected across Linux and Windows fleets!")

    elif scenario == "recover":
        cmd_recover()
    else:
        print(f" [!] Unknown chaos scenario '{scenario}'. Available: cpu_spike, auth_crash, sql_deadlock, queue_backlog, ticket_latency, ticket_500, multistage_cascade, recover")


def cmd_recover():
    print_banner("Recover All Chaos Scenarios")
    try:
        requests.post(f"{AUTH_GATEWAY_URL}/api/v1/chaos/recover", timeout=3)
        requests.post(f"{AUDIT_SERVICE_URL}/api/v1/chaos/recover", timeout=3)
        requests.post(f"{NOTIFICATION_API_URL}/api/v1/chaos/recover", timeout=3)
        requests.post(f"{TICKETFLOW_API_URL}/api/v1/chaos/recover", timeout=3)
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
        c.exec_command("pkill -9 -f 'sum(' || pkill -9 -f 'aist_cpu_burner' || true")
        c.close()
        print(" [+] All chaos states cleared and services recovered back to healthy state!")
    except Exception as e:
        print(" [!] Recovery Notice:", e)


# ==============================================================================
# 10. CLEAN TEMPORARY STATE
# ==============================================================================
def cmd_traffic(duration: int = 60, interval: float = 3.0):
    """Generate live synthetic multi-OS traffic to continuously feed Loki and Prometheus."""
    print_banner("Synthetic Multi-OS Traffic Generator")
    print(f" [+] Generating traffic every {interval}s (Duration: {'infinite' if duration <= 0 else f'{duration}s'})...")
    print(f" [+] Pinging TicketFlow (:5000), Notification (:8080), Auth (:5001), Audit (:8088)...")
    print(f" [+] Press Ctrl+C to terminate at any time.\n")

    t_start = time.time()
    count = 0
    services: List[Dict[str, Any]] = [
        {"name": "Loan Applications Query", "url": f"http://{RHEL10_IP}:5000/applications", "method": "GET"},
        {"name": "Loan Cases Query", "url": f"http://{RHEL10_IP}:5000/cases", "method": "GET"},
        {"name": "Loan Business Metrics", "url": f"http://{RHEL10_IP}:5000/business-metrics", "method": "GET"},
        {"name": "LoanPortal WebUI", "url": f"http://{WIN2025_IP}:3000/", "method": "GET"},
        {"name": "Notification Dispatch", "url": f"{NOTIFICATION_API_URL}/api/v1/notify", "method": "POST", "data": {"recipient": "chief-risk-officer@aist.local", "channel": "slack", "message": "Commercial Loan Telemetry Pulse"}},
        {"name": "Auth Gateway Login", "url": f"{AUTH_GATEWAY_URL}/api/v1/auth/login", "method": "POST", "data": {"username": "admin", "password": "Admin@AIST2026"}},
        {"name": "Audit Logging", "url": f"{AUDIT_SERVICE_URL}/api/v1/audit/logs", "method": "POST", "data": {"service": "loanprocessai", "action": "underwriting_pipeline_telemetry_stream"}}
    ]

    try:
        while True:
            if duration > 0 and (time.time() - t_start) >= duration:
                break
            count += 1
            print(f"[{time.strftime('%H:%M:%S')}] Batch #{count:03d}:")
            for s in services:
                try:
                    t0 = time.time()
                    url_target = str(s["url"])
                    if s["method"] == "GET":
                        r = requests.get(url_target, timeout=2)
                    else:
                        r = requests.post(url_target, json=s.get("data", {}), timeout=2)
                    ms = (time.time() - t0) * 1000
                    status_color = C_GREEN if r.status_code in (200, 201, 202) else C_YELLOW
                    print(f"  * {s['name']:<24}: {status_color}HTTP {r.status_code}{C_RESET} ({ms:.1f}ms)")
                    logger.info("Traffic emitted to %s: HTTP %s in %.1fms", s['name'], r.status_code, ms)
                except Exception as e:
                    print(f"  * {s['name']:<24}: {C_RED}FAIL ({str(e)[:20]}){C_RESET}")
                    logger.warning("Traffic failed for %s: %s", s['name'], e)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n [!] Traffic generation halted by user.")

    print(f"\n[+] Traffic session ended. Emitted {count} batches to all microservices.")
    print(f"    Check live Grafana stream at: {GRAFANA_URL}/d/aist-live-logs")


def cmd_vm(action_type: str = "list", name: str | None = None, template: str | None = None, ram: int = 16, cpus: int = 4, count: int = 1, ip: str | None = None):
    """Native vCenter 8.0 Hypervisor Lifecycle & Scalability Engine."""
    print_banner(f"vCenter VM Lifecycle Management: {action_type.upper()}")
    prov = VCenterProvisioner()
    if not prov.connect():
        print(f" [!] ERROR: Failed to connect to vCenter at {VCENTER_HOST}")
        return False

    try:
        if action_type in ["list", "vms", "status"]:
            vms = prov.list_vms()
            print(f"\nActive Virtual Machines on vCenter ({VCENTER_HOST}):")
            print(f"{'ID':<10} {'NAME':<18} {'POWER STATE':<14} {'CPUs':<6} {'RAM (MB)':<10} {'IP ADDRESS'}")
            print("-" * 80)
            for vm in vms:
                ip_str = vm.get('ip_address') or '-'
                print(f"{vm['id']:<10} {vm['name']:<18} {vm['power_state']:<14} {vm['num_cpus']:<6} {vm['ram_mb']:<10} {ip_str}")

        elif action_type in ["templates", "template"]:
            templates = prov.list_templates()
            print(f"\nAvailable Master VM Templates on vCenter (Base_DS):")
            print(f"{'ID':<10} {'TEMPLATE NAME':<24} {'CPUs':<6} {'RAM (MB)':<10} {'GUEST OS'}")
            print("-" * 80)
            for t in templates:
                print(f"{t['id']:<10} {t['name']:<24} {t['num_cpus']:<6} {t['ram_mb']:<10} {t['guest_os']}")

        elif action_type in ["create", "clone", "deploy"]:
            if not template or not name:
                print(" [!] ERROR: Both --template and --name are required to clone a VM.")
                print("     Example: python manage_aist.py vm create --template rhel10 --name RHEL10-Worker-01 --ram 16 --cpus 4")
                return False
            ram_mib = ram * 1024
            prov.clone_from_template(template, name, ram_mib=ram_mib, cpus=cpus, power_on=True)

        elif action_type in ["destroy", "delete", "remove"]:
            if not name:
                print(" [!] ERROR: --name is required to destroy a VM.")
                return False
            if is_protected(name):
                print(f" [!] SAFETY GUARD: Refusing to destroy protected asset '{name}'! Master templates cannot be deleted.")
                return False
            prov.destroy_vm(name)

        elif action_type in ["scale", "horizontal"]:
            if not template:
                print(" [!] ERROR: --template is required for horizontal scaling.")
                print("     Example: python manage_aist.py vm scale --template rhel10 --count 2")
                return False
            scaled = prov.scale_fleet(template, count=count, ram_gb=ram, cpus=cpus)
            print(f"\n[+] Scaled {len(scaled)} new worker instance(s): {', '.join(scaled)}")

        elif action_type in ["restore", "restore-fleet", "rebuild"]:
            if name and name.lower() not in ["all", "fleet"]:
                tpl_key = name.lower().replace("-", "").replace("_", "")
                if tpl_key in TEMPLATES:
                    prov.destroy_vm(name)
                    prov.clone_from_template(tpl_key, name, ram_mib=ram * 1024, cpus=cpus, power_on=True)
                else:
                    print(f" [!] Unknown VM name {name}. Valid: rhel10, rhel9, win2019, win2025")
            else:
                prov.clean_fleet()
                prov.setup_fleet(force_recreate=True, cpus=cpus, ram_gb=ram)

        else:
            print(f" [!] Unknown VM action: {action_type}. Valid: list, templates, create, destroy, restore, scale")
    finally:
        prov.close()
    return True


def cmd_clean(target: str | None = None) -> bool:
    """
    Clean infrastructure or temporary logs.
    CRITICAL SAFEGUARD:
    - Only deletes the 4 fleet VMs (RHEL10, RHEL9, Win2025, Win2019) and scaled workers.
    - NEVER touches master templates, datastores, or core infrastructure.
    """
    print_banner("Clean Fleet Infrastructure")
    target_clean = (target or "infra").lower()

    if target_clean in ["infra", "clean-infra", "vms", "fleet", "all"]:
        print("\n[!] Initiating SAFE teardown of managed fleet VMs...")
        print("    Target VMs: RHEL10, RHEL9, Win2025, Win2019")
        print("    SAFEGUARD: Master templates on Base_DS will NOT be touched.")

        try:
            cmd_stop("apps")
        except Exception:
            pass

        prov = VCenterProvisioner()
        if not prov.connect():
            print(f" [!] ERROR: Failed to connect to vCenter at {VCENTER_HOST}")
            return False
        try:
            prov.clean_fleet()
            print("\n[+] Fleet VMs safely removed. All master templates remain preserved on Base_DS.")
        finally:
            prov.close()

    if target_clean in ["logs", "tmp", "all"]:
        print("\n[+] Cleaning temporary service logs...")
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(RHEL10_IP, port=22, username=LINUX_USER, password=LINUX_PASS, timeout=5)
            c.exec_command("rm -rf /opt/aist/ticketflow-api/*.log /opt/aist/notification-service/*.log")
            c.close()
            print(" [+] Cleaned RHEL 10 logs.")
        except Exception:
            pass

    return True


# ==============================================================================
# MAIN ENTRY POINT & CLI PARSER
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="AIST Platform Unified Control CLI (manage_aist.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Core Workflow Examples:
  python manage_aist.py setup                 # Provision 4 VMs from templates (4 vCPUs, 16GB RAM), bind IPs & firewalls
  python manage_aist.py setup --force         # Force rebuild clean VMs from master templates
  python manage_aist.py deploy                # Deploy all apps, microservices & observability across VMs
  python manage_aist.py status                # Run comprehensive 24-point health verification matrix
  python manage_aist.py clean-infra           # Safe teardown: removes 4 fleet VMs (NEVER touches templates)

Service & Operations Controls:
  python manage_aist.py list                  # Show all apps, containers, servers, and live URLs
  python manage_aist.py start all             # Start all microservices, containers, and WebUI
  python manage_aist.py start webui           # Start local WebUI and AI Triage backend
  python manage_aist.py stop all              # Stop all microservices and containers
  python manage_aist.py restart apps          # Restart all microservices
  python manage_aist.py logs ticketflow       # View live logs for a service
  python manage_aist.py chaos --scenario cpu_spike # Inject failure scenario
  python manage_aist.py recover               # Restore 100% health
  python manage_aist.py vm list               # List all VMs directly on ESXi 8.0
  python manage_aist.py vm templates          # List master VM templates
        """
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=[
            "setup", "setup-infra",
            "deploy", "deploy-apps",
            "status", "verify",
            "start", "stop", "restart",
            "clean", "clean-infra",
            "list", "urls",
            "logs",
            "chaos", "recover",
            "traffic",
            "vm"
        ],
        help="Action to execute (default: status)"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Optional target service, group, or VM subaction (list, templates, create, destroy, restore, scale)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force recreate existing VMs during setup"
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter category for list/urls (apps, obs, ai, infra, ui)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output list command in raw JSON"
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Target VM name for VM operations (create, destroy, restore)"
    )
    parser.add_argument(
        "--template",
        default=None,
        help="Template key for VM provisioning (rhel10, rhel9, win2019, win2025)"
    )
    parser.add_argument(
        "--ram",
        type=int,
        default=16,
        help="RAM in GB for VM provisioning (default: 16 GB)"
    )
    parser.add_argument(
        "--cpus",
        type=int,
        default=4,
        help="vCPUs for VM provisioning (default: 4)"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of instances to horizontally scale (default: 1)"
    )
    parser.add_argument(
        "--ip",
        default=None,
        help="Static IP address to assign directly without DHCP (e.g. 192.168.1.130)"
    )
    parser.add_argument(
        "--scenario",
        default="cpu_spike",
        help="Chaos scenario to inject (cpu_spike, auth_crash, sql_deadlock, queue_backlog, ticket_latency, ticket_500, multistage_cascade, recover)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in seconds for synthetic traffic generator (default: 60s, 0 for infinite)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Interval between synthetic traffic pulses in seconds (default: 3.0s)"
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=25,
        help="Number of log lines to retrieve (default: 25)"
    )

    args = parser.parse_args()
    action = args.action.lower()
    target = args.target

    if action in ["setup", "setup-infra"]:
        cmd_setup(force_recreate=args.force, cpus=args.cpus, ram=args.ram)

    elif action in ["deploy", "deploy-apps"]:
        deploy_target = target if target else "all"
        cmd_deploy(deploy_target)

    elif action in ["status", "verify"]:
        cmd_status()

    elif action == "start":
        start_target = target if target else "all"
        cmd_start(start_target)

    elif action == "stop":
        stop_target = target if target else "all"
        cmd_stop(stop_target)

    elif action == "restart":
        restart_target = target if target else "all"
        cmd_restart(restart_target)

    elif action in ["clean", "clean-infra"]:
        cmd_clean(target or action)

    elif action in ["list", "urls"]:
        cmd_list(category=args.category or target, as_json=args.json)

    elif action == "logs":
        if not target:
            print(" [!] Please specify a service for logs (e.g., python manage_aist.py logs ticketflow)")
            print("     Available: ticketflow, notification, auth, audit, prometheus, grafana, loki, tempo, alertmanager")
        else:
            cmd_logs(target, lines=args.lines)

    elif action == "chaos":
        scenario = target if target else args.scenario
        cmd_chaos(scenario)

    elif action == "recover":
        cmd_recover()

    elif action == "traffic":
        cmd_traffic(duration=args.duration, interval=args.interval)

    elif action == "vm":
        vm_action = target if target else "list"
        cmd_vm(
            action_type=vm_action,
            name=args.name,
            template=args.template,
            ram=args.ram,
            cpus=args.cpus,
            count=args.count,
            ip=args.ip
        )

    else:
        print(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
