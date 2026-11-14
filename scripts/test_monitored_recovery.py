"""Offline tests for the three-attempt circuit-breaker policy."""

import os
import sys
import tempfile
import gc

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "ai-triage", "webui", "backend", "app"))

from self_healing import MonitoredRecovery  # noqa: E402
from state_store import AistStateStore  # noqa: E402


def with_store():
    temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp.close()
    return temp.name, AistStateStore(temp.name)


path, store = with_store()
try:
    failures = MonitoredRecovery(store, lambda _: (True, "restart accepted"), lambda *_: (False, "health probe failed"))
    result = failures.recover("inc-1", "auth-gateway", "recover_auth_gateway", "gateway unavailable")
    assert result["status"] == "ESCALATED" and result["attempt"] == 3
    assert store.circuit_state("auth-gateway", "recover_auth_gateway") == "TRIPPED"
    assert failures.recover("inc-2", "auth-gateway", "recover_auth_gateway", "repeat") ["reason"] == "Circuit breaker is tripped"
finally:
    gc.collect()
    os.unlink(path)

path, store = with_store()
try:
    healthy = MonitoredRecovery(store, lambda _: (True, "restart accepted"), lambda *_: (True, "healthy for 30 seconds"))
    result = healthy.recover("inc-3", "notification-service", "recover_notification_queue", "backlog")
    assert result["status"] == "RESOLVED" and result["attempt"] == 1
    assert healthy.recover("inc-4", "ticketflow-api", None, "no matching runbook")["reason"] == "No approved runbook action"
finally:
    gc.collect()
    os.unlink(path)

print("Monitored recovery policy tests passed")
