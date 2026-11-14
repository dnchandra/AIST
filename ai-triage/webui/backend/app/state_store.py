"""
Durable SQLite State and Audit Store for AIST Platform.
Configured with Write-Ahead Logging (WAL) mode for concurrent access across
FastAPI, LangGraph agents, and FastMCP diagnostic tools.
"""

from __future__ import annotations

import os
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class AistStateStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS service_state (
                  service_id TEXT PRIMARY KEY, desired_state TEXT NOT NULL DEFAULT 'RUNNING',
                  observed_state TEXT NOT NULL DEFAULT 'UNKNOWN', updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS service_operations (
                  operation_id TEXT PRIMARY KEY, service_id TEXT NOT NULL, action TEXT NOT NULL,
                  requested_by TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL,
                  requested_at REAL NOT NULL, completed_at REAL, output TEXT, verification TEXT
                );
                CREATE TABLE IF NOT EXISTS remediation_attempts (
                  attempt_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, service_id TEXT NOT NULL,
                  action_id TEXT NOT NULL, attempt_number INTEGER NOT NULL, status TEXT NOT NULL,
                  created_at REAL NOT NULL, verification TEXT
                );
                CREATE TABLE IF NOT EXISTS circuit_breakers (
                  service_id TEXT NOT NULL, action_id TEXT NOT NULL, state TEXT NOT NULL,
                  reason TEXT, tripped_at REAL, PRIMARY KEY(service_id, action_id)
                );
                CREATE TABLE IF NOT EXISTS tickets (
                  ticket_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, service_id TEXT NOT NULL,
                  reason TEXT NOT NULL, analysis TEXT NOT NULL, created_at REAL NOT NULL, status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incidents (
                  incident_id TEXT PRIMARY KEY, title TEXT, state TEXT NOT NULL,
                  target_os TEXT, severity TEXT, payload TEXT, report TEXT,
                  created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mcp_tool_audit (
                  execution_id TEXT PRIMARY KEY, tool_name TEXT NOT NULL,
                  input_params TEXT, status TEXT NOT NULL, duration_ms REAL,
                  executed_at REAL NOT NULL, error TEXT
                );
            """)

    # --- Incidents Persistence ---
    def save_incident(self, incident: Dict[str, Any]) -> None:
        incident_id = incident.get("id") or incident.get("incident_id")
        if not incident_id:
            return
        now = time.time()
        title = incident.get("title", f"Incident {incident_id}")
        state = incident.get("state", "INVESTIGATING")
        target_os = incident.get("target_os", "unknown")
        severity = incident.get("severity", "critical")
        created_at = incident.get("created_at", now)
        report = incident.get("final_report") or incident.get("root_cause_analysis") or ""
        payload_str = json.dumps(incident)

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO incidents(incident_id, title, state, target_os, severity, payload, report, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    title=excluded.title, state=excluded.state, target_os=excluded.target_os,
                    severity=excluded.severity, payload=excluded.payload, report=excluded.report,
                    updated_at=excluded.updated_at
            """, (incident_id, title, state, target_os, severity, payload_str, report, created_at, now))

    def load_all_incidents(self) -> Dict[str, Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM incidents ORDER BY created_at DESC").fetchall()
        result = {}
        for r in rows:
            try:
                data = json.loads(r["payload"])
                iid = data.get("id") or data.get("incident_id")
                if iid:
                    result[iid] = data
            except Exception:
                pass
        return result

    def clear_all_incidents(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM incidents")

    # --- MCP Tool Audit Logging ---
    def log_mcp_tool_execution(self, tool_name: str, input_params: Any, status: str, duration_ms: float, error: str = "") -> str:
        exec_id = f"mcp-exec-{uuid.uuid4().hex[:12]}"
        now = time.time()
        try:
            params_str = json.dumps(input_params, default=str)[:4000]
        except Exception:
            params_str = str(input_params)[:4000]

        with self._connect() as conn:
            conn.execute("""
                INSERT INTO mcp_tool_audit(execution_id, tool_name, input_params, status, duration_ms, executed_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (exec_id, tool_name, params_str, status, duration_ms, now, error[:2000]))
        return exec_id

    def list_mcp_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM mcp_tool_audit ORDER BY executed_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    # --- Services & Operations ---
    def services(self) -> Dict[str, Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM service_state").fetchall()
        return {row["service_id"]: dict(row) for row in rows}

    def set_service_state(self, service_id: str, desired: str, observed: str = "UNKNOWN") -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO service_state(service_id, desired_state, observed_state, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(service_id) DO UPDATE SET desired_state=excluded.desired_state,
                observed_state=excluded.observed_state, updated_at=excluded.updated_at
            """, (service_id, desired, observed, now))

    def create_operation(self, service_id: str, action: str, reason: str, requested_by: str = "operator") -> str:
        operation_id = f"op-{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute("INSERT INTO service_operations VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
                         (operation_id, service_id, action, requested_by, reason, "REQUESTED", time.time()))
        return operation_id

    def finish_operation(self, operation_id: str, status: str, output: str = "", verification: str = "") -> None:
        with self._connect() as conn:
            conn.execute("UPDATE service_operations SET status=?, completed_at=?, output=?, verification=? WHERE operation_id=?",
                         (status, time.time(), output[:8000], verification[:8000], operation_id))

    def list_operations(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM service_operations ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def create_attempt(self, incident_id: str, service_id: str, action_id: str) -> Dict[str, Any]:
        with self._connect() as conn:
            number = conn.execute("SELECT COUNT(*) FROM remediation_attempts WHERE incident_id=? AND service_id=? AND action_id=?",
                                  (incident_id, service_id, action_id)).fetchone()[0] + 1
            attempt = {"attempt_id": f"attempt-{uuid.uuid4().hex[:12]}", "attempt_number": number}
            conn.execute("INSERT INTO remediation_attempts VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                         (attempt["attempt_id"], incident_id, service_id, action_id, number, "RUNNING", time.time()))
        return attempt

    def finish_attempt(self, attempt_id: str, status: str, verification: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE remediation_attempts SET status=?, verification=? WHERE attempt_id=?",
                         (status, verification[:8000], attempt_id))

    def trip_circuit(self, service_id: str, action_id: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute("""INSERT INTO circuit_breakers VALUES (?, ?, 'TRIPPED', ?, ?)
                ON CONFLICT(service_id, action_id) DO UPDATE SET state='TRIPPED', reason=excluded.reason, tripped_at=excluded.tripped_at
            """, (service_id, action_id, reason, time.time()))

    def circuit_state(self, service_id: str, action_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT state FROM circuit_breakers WHERE service_id=? AND action_id=?", (service_id, action_id)).fetchone()
        return row["state"] if row else "CLOSED"

    def create_ticket(self, incident_id: str, service_id: str, reason: str, analysis: str) -> str:
        ticket_id = f"aist-ticket-{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            conn.execute("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, 'OPEN')",
                         (ticket_id, incident_id, service_id, reason, analysis[:12000], time.time()))
        return ticket_id

    def metrics(self) -> Dict[str, int]:
        with self._connect() as conn:
            return {
                "operations": conn.execute("SELECT COUNT(*) FROM service_operations").fetchone()[0],
                "failed_operations": conn.execute("SELECT COUNT(*) FROM service_operations WHERE status='FAILED'").fetchone()[0],
                "attempts": conn.execute("SELECT COUNT(*) FROM remediation_attempts").fetchone()[0],
                "failed_attempts": conn.execute("SELECT COUNT(*) FROM remediation_attempts WHERE status != 'VERIFIED'").fetchone()[0],
                "tripped_circuits": conn.execute("SELECT COUNT(*) FROM circuit_breakers WHERE state='TRIPPED'").fetchone()[0],
                "open_tickets": conn.execute("SELECT COUNT(*) FROM tickets WHERE status='OPEN'").fetchone()[0],
                "mcp_tool_calls": conn.execute("SELECT COUNT(*) FROM mcp_tool_audit").fetchone()[0],
            }


_global_state_store: Optional[AistStateStore] = None

def get_state_store() -> AistStateStore:
    global _global_state_store
    if _global_state_store is None:
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "aist_state.db"))
        _global_state_store = AistStateStore(db_path)
    return _global_state_store
