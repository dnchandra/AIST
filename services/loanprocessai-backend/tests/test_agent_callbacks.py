"""test_agent_callbacks.py

Regression test for local-mode agent callbacks (logging + failure rows).
Runs against a temporary SQLite database so local runtime DB is untouched.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import local_tools  # noqa: E402

from typing import Any

tmp = Path(tempfile.mkdtemp(prefix="cla-cb-"))
local_tools._DIR = tmp
local_tools._DOCS = tmp / "documents"
local_tools._DB = tmp / "test.db"


class FakeCtx:
    def __init__(self, agent_name: str, state: dict):
        self.agent_name = agent_name
        self.state = state


def make_ctx(agent_name: str, state: dict) -> Any:
    return FakeCtx(agent_name, state)


def run_case() -> bool:
    out = []
    # 1. Successful run: hydrate a stale value first, then start -> persist.
    state = {
        "case_id": "CASE-TEST",
        "application_id": "APP-TEST",
        # stale value from a previous run (exactly what build_initial_state hydrates)
        "kyc_output": "OLD STALE KYC TEXT FROM A PREVIOUS RUN",
    }
    start = local_tools.make_start_callback("KYC_Concierge_Agent", "kyc_output")
    persist = local_tools.make_persist_callback("KYC_Concierge_Agent", "kyc_output")
    start(make_ctx("KYC_Concierge_Agent", state))
    out.append(("stale cleared on start", state["kyc_output"] == ""))
    state["kyc_output"] = "NEW KYC REPORT " + "x" * 40
    persist(make_ctx("KYC_Concierge_Agent", state))

    # 2. Failed run: agent produced nothing -> must NOT keep the stale text and
    #    must leave a truthful trail (log + failed row).
    state2 = {
        "case_id": "CASE-TEST",
        "application_id": "APP-TEST",
        "decision_output": "OLD STALE DECISION TEXT FROM A PREVIOUS RUN",
    }
    start2 = local_tools.make_start_callback("Decision_Support_Agent", "decision_output")
    persist2 = local_tools.make_persist_callback("Decision_Support_Agent", "decision_output")
    start2(make_ctx("Decision_Support_Agent", state2))
    persist2(make_ctx("Decision_Support_Agent", state2))
    out.append(("failed run keeps no stale text", not state2.get("decision_output")))

    with sqlite3.connect(local_tools._DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT agent_name, status, error_message, length(output) AS out_len "
            "FROM agent_runs ORDER BY status"
        ).fetchall()]
    out.append(("completed row written", any(r["agent_name"] == "KYC_Concierge_Agent"
                                             and r["status"] == "completed" for r in rows)))
    out.append(("failed row written", any(r["agent_name"] == "Decision_Support_Agent"
                                          and r["status"] == "failed" for r in rows)))
    out.append(("failed row carries error", any(
        (r["error_message"] or "") == "no_output_in_state" for r in rows)))
    # The completed row must hold the NEW text, never the hydrated stale text.
    with sqlite3.connect(local_tools._DB) as conn:
        text = json.loads(conn.execute(
            "SELECT output FROM agent_runs WHERE agent_name='KYC_Concierge_Agent'"
        ).fetchone()[0])["text"]
    out.append(("completed row holds fresh text", text.startswith("NEW KYC REPORT")))

    # 3. load_case_context must emit a STARTED marker for the root agent.
    ctx = make_ctx("Commercial_Lending_Orchestrator", {"case_id": "CASE-TEST"})
    local_tools.load_case_context(ctx)
    out.append(("root STARTED marker", "_started_mono::Commercial_Lending_Orchestrator"
                in ctx.state))

    for name, ok in out:
        print(("PASS  " if ok else "FAIL  ") + name)
    return all(ok for _, ok in out)


if __name__ == "__main__":
    ok = run_case()
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    sys.exit(0 if ok else 1)
