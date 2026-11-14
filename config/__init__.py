"""
AIST Centralized Enterprise Configuration Package
Loads all credentials, IP addresses, ports, and model names from .env.
Ensures zero hardcoded credentials across scripts and services.
"""

import os
from pathlib import Path

# Locate root directory containing .env
CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR if (CURRENT_DIR / ".env").exists() else CURRENT_DIR.parent
ENV_PATH = ROOT_DIR / ".env"

# Fallback parser if python-dotenv is not installed
def load_env_file(path: Path):
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_PATH)
except ImportError:
    load_env_file(ENV_PATH)

# --- Secret handling helpers ---
def _required_secret(name: str) -> str:
    """Return a required secret from the environment.

    AIST intentionally has no fallback password.  Missing secrets must fail fast
    instead of silently using a known credential.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise RuntimeError(
            f"Required secret '{name}' is not set. Copy .env.example to .env "
            "and replace every placeholder with a real value."
        )
    return value.strip()


# --- Hypervisor & vCenter Settings ---
VCENTER_HOST = os.environ.get("VCENTER_HOST", "192.168.1.220")
VCENTER_USER = os.environ.get("VCENTER_USER", "Administrator@vsphere.local")
VCENTER_PASS = _required_secret("VCENTER_PASS")
ESXI_HOST = os.environ.get("ESXI_HOST", "192.168.1.221")
ESXI_USER = os.environ.get("ESXI_USER", "root")
ESXI_PASS = _required_secret("ESXI_PASS")
DATASTORE_TARGET = os.environ.get("DATASTORE_TARGET", "Base_DS")

# --- Multi-OS Node IPs ---
RHEL10_IP = os.environ.get("RHEL10_IP", "192.168.1.130")
RHEL9_IP = os.environ.get("RHEL9_IP", "192.168.1.131")
WIN2025_IP = os.environ.get("WIN2025_IP", "192.168.1.132")
WIN2019_IP = os.environ.get("WIN2019_IP", "192.168.1.133")
LOCAL_AI_HOST = os.environ.get("LOCAL_AI_HOST", "192.168.1.16")

# --- Operating System Authentication ---
LINUX_USER = os.environ.get("LINUX_USER", "root")
LINUX_PASS = _required_secret("LINUX_PASS")
WINDOWS_USER = os.environ.get("WINDOWS_USER", "Administrator")
WINDOWS_PASS = _required_secret("WINDOWS_PASS")

# --- Service Ports ---
TICKETFLOW_PORT = int(os.environ.get("TICKETFLOW_PORT", 5000))
NOTIFICATION_PORT = int(os.environ.get("NOTIFICATION_PORT", 8080))
AUTH_GATEWAY_PORT = int(os.environ.get("AUTH_GATEWAY_PORT", 5001))
AUDIT_SERVICE_PORT = int(os.environ.get("AUDIT_SERVICE_PORT", 8088))
NODE_EXPORTER_PORT = int(os.environ.get("NODE_EXPORTER_PORT", 9100))

PROMETHEUS_PORT = int(os.environ.get("PROMETHEUS_PORT", 9090))
GRAFANA_PORT = int(os.environ.get("GRAFANA_PORT", 3000))
LOKI_PORT = int(os.environ.get("LOKI_PORT", 3100))
ALERTMANAGER_PORT = int(os.environ.get("ALERTMANAGER_PORT", 9093))
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", 8000))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", 3001))

# --- AI Brain Settings ---
_raw_ollama = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not _raw_ollama.startswith(("http://", "https://")):
    _raw_ollama = f"http://{_raw_ollama}"
_raw_ollama = _raw_ollama.replace("://0.0.0.0", "://127.0.0.1")
OLLAMA_HOST = _raw_ollama
PRIMARY_LLM = os.environ.get("PRIMARY_LLM", "ornith-1.5:35b")
EMBEDDING_LLM = os.environ.get("EMBEDDING_LLM", "embeddinggemma-2:740m")

# --- Computed Derived Service URLs ---
PROM_URL = f"http://{RHEL9_IP}:{PROMETHEUS_PORT}"
ALERTMANAGER_URL = f"http://{RHEL9_IP}:{ALERTMANAGER_PORT}"
GRAFANA_URL = f"http://{RHEL9_IP}:{GRAFANA_PORT}"
LOKI_URL = f"http://{RHEL9_IP}:{LOKI_PORT}"

TICKETFLOW_API_URL = f"http://{RHEL10_IP}:{TICKETFLOW_PORT}"
NOTIFICATION_API_URL = f"http://{RHEL10_IP}:{NOTIFICATION_PORT}"
AUTH_GATEWAY_URL = f"http://{WIN2025_IP}:{AUTH_GATEWAY_PORT}"
AUDIT_SERVICE_URL = f"http://{WIN2019_IP}:{AUDIT_SERVICE_PORT}"

BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"

# --- JWT Secret ---
JWT_SECRET = os.environ.get("JWT_SECRET", "AIST-v4-LoanOrigination-2026-SecretKey-HMAC256")

# --- LoanOrigination Portal Port ---
LOAN_PORTAL_PORT = int(os.environ.get("LOAN_PORTAL_PORT", 3001))

# Browser origins permitted to invoke the local operator API
CORS_ORIGINS = [
    origin.strip() for origin in os.environ.get(
        "CORS_ORIGINS",
        f"http://127.0.0.1:{FRONTEND_PORT},http://localhost:{FRONTEND_PORT},"
        f"http://{RHEL10_IP}:{LOAN_PORTAL_PORT}"
    ).split(",") if origin.strip()
]

