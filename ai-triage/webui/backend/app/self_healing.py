"""Deterministic monitored-recovery policy.

The engine has no model dependency.  It receives an approved action selected
by policy, runs it through an injected executor, and requires an injected
health observer to report a stable 30-second recovery window.
"""

from __future__ import annotations

from typing import Callable, Dict, Tuple

from state_store import AistStateStore


Execute = Callable[[str], Tuple[bool, str]]
Observe = Callable[[str, int], Tuple[bool, str]]


class MonitoredRecovery:
    def __init__(self, store: AistStateStore, execute: Execute, observe: Observe, max_attempts: int = 3, observation_seconds: int = 30):
        self.store = store
        self.execute = execute
        self.observe = observe
        self.max_attempts = max_attempts
        self.observation_seconds = observation_seconds

    def recover(self, incident_id: str, service_id: str, action_id: str | None, analysis: str) -> Dict[str, object]:
        if not action_id:
            ticket_id = self.store.create_ticket(incident_id, service_id, "NO_APPROVED_RUNBOOK", analysis)
            return {"status": "ESCALATED", "reason": "No approved runbook action", "ticket_id": ticket_id}

        if self.store.circuit_state(service_id, action_id) == "TRIPPED":
            ticket_id = self.store.create_ticket(incident_id, service_id, "CIRCUIT_BREAKER_TRIPPED", analysis)
            return {"status": "ESCALATED", "reason": "Circuit breaker is tripped", "ticket_id": ticket_id}

        for _ in range(self.max_attempts):
            attempt = self.store.create_attempt(incident_id, service_id, action_id)
            executed, execution_detail = self.execute(action_id)
            if executed:
                healthy, observation_detail = self.observe(service_id, self.observation_seconds)
            else:
                healthy, observation_detail = False, "Action execution failed; observation skipped"
            verification = f"execution={execution_detail}; observation={observation_detail}"
            self.store.finish_attempt(attempt["attempt_id"], "VERIFIED" if healthy else "FAILED", verification)
            if healthy:
                return {"status": "RESOLVED", "attempt": attempt["attempt_number"], "verification": verification}

        reason = f"Recovery failed {self.max_attempts} times; automation locked for this service/action"
        self.store.trip_circuit(service_id, action_id, reason)
        ticket_id = self.store.create_ticket(incident_id, service_id, "RECOVERY_FAILED_THREE_TIMES", analysis + "\n" + reason)
        return {"status": "ESCALATED", "reason": reason, "ticket_id": ticket_id, "attempt": self.max_attempts}
