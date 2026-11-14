"""Local persistence adapter used by the Azure-ready development baseline.

It mirrors the data-facing functions exported by ``tools.py`` so the ADK
agents and FastAPI API can run without BigQuery or Cloud Storage credentials.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

_DIR_ENV = os.getenv("LOCAL_DATA_DIR") or os.getenv("LOANAPP_DATA_DIR")
_DIR = (
    Path(_DIR_ENV).expanduser().resolve()
    if _DIR_ENV
    else Path(__file__).resolve().parent / "data"
)
_DOCS = _DIR / "documents"
_DB = _DIR / "loan_origination.db"
_AGENTS = {
    "Document_Intake_Agent": ("document_intake_output", "document_intake"),
    "KYC_Concierge_Agent": ("kyc_output", "kyc"),
    "Financial_Spreading_Agent": ("financial_output", "financial"),
    "Credit_Memo_Agent": ("memo_output", "memo"),
    "Decision_Support_Agent": ("decision_output", "decision"),
    "Closing_Package_Agent": ("closing_output", "closing"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Structured per-agent logger (same channel/format as tools.py)
# ---------------------------------------------------------------------------
# Local mode swaps the persistence layer, but the operator still needs the same
# grep-friendly agent trail in logs/backend.log, otherwise a failed run is
# invisible:
#   [AGENT] KYC_Concierge_Agent   STARTED   case=CASE-ABC123
#   [AGENT] KYC_Concierge_Agent   COMPLETED case=CASE-ABC123  dur=4123ms  out_chars=842
#   [AGENT] KYC_Concierge_Agent   FAILED    case=CASE-ABC123  dur=120ms   error=no_output_in_state
_logger = logging.getLogger("cla.agent")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    ))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def _log_event(agent_name: str, status: str, case_id: str | None,
               duration_ms: int | None = None, extra: str = "") -> None:
    parts = [f"[AGENT] {agent_name:<30s} {status:<9s}"]
    if case_id:
        parts.append(f"case={case_id}")
    if duration_ms is not None:
        parts.append(f"dur={duration_ms}ms")
    if extra:
        parts.append(extra)
    _logger.info("  ".join(parts))


def _agent_name_from_context(callback_context: CallbackContext) -> str:
    """Best-effort agent name for a callback context (same logic as tools.py)."""
    return str(
        getattr(callback_context, "agent_name", None)
        or getattr(getattr(callback_context, "agent", None), "name", None)
        or getattr(getattr(callback_context, "_invocation_context", None), "agent", None)
        and getattr(callback_context._invocation_context.agent, "name", None)  # type: ignore[attr-defined]
        or "unknown_agent"
    )


def _connect() -> sqlite3.Connection:
    _DIR.mkdir(exist_ok=True)
    _DOCS.mkdir(exist_ok=True)
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS applications (
          application_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, status TEXT NOT NULL,
          submitted_at TEXT NOT NULL, updated_at TEXT NOT NULL, owner_email TEXT,
          business_legal_name TEXT, loan_amount TEXT, loan_purpose TEXT, form_data TEXT NOT NULL,
          reviewed_by TEXT, review_note TEXT);
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, filename TEXT NOT NULL,
          local_path TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
          doc_type TEXT, uploaded_at TEXT NOT NULL, uploaded_by TEXT);
        CREATE TABLE IF NOT EXISTS cases (
          case_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, assigned_rm TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_runs (
          run_id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, case_id TEXT, application_id TEXT,
          status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL, output TEXT,
          summary TEXT, error_message TEXT);
        CREATE TABLE IF NOT EXISTS case_audit_log (
          audit_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, decision TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL);
    """)
    _seed_default_portfolio(conn)
    return conn


def _seed_default_portfolio(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, val TEXT)")
    has_seeded = conn.execute("SELECT val FROM system_settings WHERE key='portfolio_seeded'").fetchone()
    if has_seeded:
        return
    count = conn.execute("SELECT count(*) FROM applications").fetchone()[0]
    if count > 0:
        conn.execute("INSERT OR REPLACE INTO system_settings VALUES ('portfolio_seeded', '1')")
        return
    now = _now()
    portfolio_apps = [
        ("APP-CRE-101", "TKT-CRE-101", "Approved", now, now, "cfo@apexlogistics.com", "Apex Global Logistics Hub LLC", "4500000", "Commercial Real Estate Warehouse Facility", json.dumps({"businessLegalName": "Apex Global Logistics Hub LLC", "loanAmount": "4500000", "loanPurpose": "Commercial Real Estate Warehouse Facility", "yearsInBusiness": 8, "annualRevenue": 18500000}), "sr-underwriter-david", "Strong collateral coverage and 1.45x DSCR."),
        ("APP-CRE-102", "TKT-CRE-102", "Approved", now, now, "finance@beaconretail.com", "Beacon Strip Center Properties", "2200000", "Commercial Property Refinancing", json.dumps({"businessLegalName": "Beacon Strip Center Properties", "loanAmount": "2200000", "loanPurpose": "Commercial Property Refinancing", "yearsInBusiness": 12, "annualRevenue": 8200000}), "sr-underwriter-david", "Low LTV, stable multi-tenant grocery anchor."),
        ("APP-CRE-103", "TKT-CRE-103", "In Review", now, now, "dr.patel@crestviewhealth.com", "Crestview Outpatient Surgical Pavilion", "3800000", "Healthcare Facility Construction", json.dumps({"businessLegalName": "Crestview Outpatient Surgical Pavilion", "loanAmount": "3800000", "loanPurpose": "Healthcare Facility Construction", "yearsInBusiness": 5, "annualRevenue": 14200000}), None, None),
        ("APP-CRE-104", "TKT-CRE-104", "Pending Documents", now, now, "ops@pacificmaritime.com", "Pacific Maritime Container Terminal", "1500000", "Port Working Capital & Crane Expansion", json.dumps({"businessLegalName": "Pacific Maritime Container Terminal", "loanAmount": "1500000", "loanPurpose": "Port Working Capital", "yearsInBusiness": 4, "annualRevenue": 6100000}), None, "Awaiting updated proof of physical address and lease agreement."),
        ("APP-CRE-105", "TKT-CRE-105", "In Review", now, now, "cfo@highpointind.com", "Highpoint Industrial Manufacturing Park", "5000000", "Heavy Machinery & Plant Refurbishment", json.dumps({"businessLegalName": "Highpoint Industrial Manufacturing Park", "loanAmount": "5000000", "loanPurpose": "Industrial Plant Expansion", "yearsInBusiness": 15, "annualRevenue": 29000000}), None, None),
        ("APP-CRE-106", "TKT-CRE-106", "Approved", now, now, "treasury@summittech.io", "Summit Technology Labs Incubator", "1200000", "Equipment Lease Facility", json.dumps({"businessLegalName": "Summit Technology Labs Incubator", "loanAmount": "1200000", "loanPurpose": "Equipment Lease Facility", "yearsInBusiness": 6, "annualRevenue": 9500000}), "sr-underwriter-david", "High cash reserve, zero debt default history."),
        ("APP-CRE-107", "TKT-CRE-107", "Rejected", now, now, "investor@deltahotels.com", "Delta Luxury Hospitality Suites", "6100000", "Hotel CRE Renovation & Refinance", json.dumps({"businessLegalName": "Delta Luxury Hospitality Suites", "loanAmount": "6100000", "loanPurpose": "Hotel CRE Renovation", "yearsInBusiness": 3, "annualRevenue": 4200000}), "credit-committee-chair", "DSCR 0.88x is below minimum policy guideline of 1.20x."),
        ("APP-CRE-108", "TKT-CRE-108", "Submitted", now, now, "logistics@horizoncold.com", "Horizon Cold Storage Distribution", "2900000", "Cold Chain Refrigeration Facility", json.dumps({"businessLegalName": "Horizon Cold Storage Distribution", "loanAmount": "2900000", "loanPurpose": "Cold Chain Refrigeration Facility", "yearsInBusiness": 7, "annualRevenue": 11000000}), None, None),
        ("APP-CRE-109", "TKT-CRE-109", "Escalated", now, now, "treasury@blueridgedist.com", "Blue Ridge Supply Chain Fleet", "3400000", "Commercial Fleet Acquisition", json.dumps({"businessLegalName": "Blue Ridge Supply Chain Fleet", "loanAmount": "3400000", "loanPurpose": "Commercial Fleet Acquisition", "yearsInBusiness": 9, "annualRevenue": 15800000}), None, "Complex multi-entity corporate guarantee requires senior committee review."),
        ("APP-CRE-110", "TKT-CRE-110", "Approved", now, now, "exec@metroplexdevelopment.com", "Metroplex Mixed-Use Tower Phase II", "8500000", "Commercial Real Estate Development", json.dumps({"businessLegalName": "Metroplex Mixed-Use Tower Phase II", "loanAmount": "8500000", "loanPurpose": "Commercial Real Estate Development", "yearsInBusiness": 18, "annualRevenue": 48000000}), "credit-committee-chair", "Prime Tier-1 metropolitan asset, 62% pre-leased."),
        ("APP-CRE-111", "TKT-CRE-111", "In Review", now, now, "finance@keystonebio.com", "Keystone BioPharm Cleanroom Labs", "4800000", "Biotech Cleanroom Facility", json.dumps({"businessLegalName": "Keystone BioPharm Cleanroom Labs", "loanAmount": "4800000", "loanPurpose": "Biotech Cleanroom Facility", "yearsInBusiness": 6, "annualRevenue": 16400000}), None, None),
        ("APP-CRE-112", "TKT-CRE-112", "Pending Documents", now, now, "charter@vantageair.com", "Vantage Private Aviation Terminal", "3200000", "Private Hangar Long-Term Leasehold", json.dumps({"businessLegalName": "Vantage Private Aviation Terminal", "loanAmount": "3200000", "loanPurpose": "Private Hangar Leasehold", "yearsInBusiness": 4, "annualRevenue": 7900000}), None, "Awaiting FAA ground-lease certification from municipal airport authority."),
    ]
    conn.executemany("INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", portfolio_apps)
    portfolio_cases = [
        ("CASE-CRE-101", "APP-CRE-101", "rm-sarah-jenkins", "Approved", now, now),
        ("CASE-CRE-102", "APP-CRE-102", "rm-sarah-jenkins", "Approved", now, now),
        ("CASE-CRE-103", "APP-CRE-103", "rm-michael-chang", "In Review", now, now),
        ("CASE-WEAK-KYC-SIM", "APP-CRE-104", "rm-sarah-jenkins", "Pending Documents", now, now),
        ("CASE-DEMO-SIM", "APP-CRE-105", "rm-michael-chang", "In Review", now, now),
        ("CASE-CRE-106", "APP-CRE-106", "rm-michael-chang", "Approved", now, now),
        ("CASE-CRE-107", "APP-CRE-107", "rm-sarah-jenkins", "Rejected", now, now),
        ("CASE-LATENCY-01", "APP-CRE-108", "rm-michael-chang", "Submitted", now, now),
        ("CASE-CONTEXT-SIM", "APP-CRE-109", "rm-sarah-jenkins", "Escalated", now, now),
        ("CASE-CRE-110", "APP-CRE-110", "rm-sarah-jenkins", "Approved", now, now),
        ("CASE-CRE-111", "APP-CRE-111", "rm-michael-chang", "In Review", now, now),
        ("CASE-CRE-112", "APP-CRE-112", "rm-sarah-jenkins", "Pending Documents", now, now),
    ]
    conn.executemany("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)", portfolio_cases)
    conn.commit()


def seed_portfolio_if_empty() -> int:
    with _connect() as conn:
        _seed_default_portfolio(conn)
        return conn.execute("SELECT count(*) FROM applications").fetchone()[0]


def _id(prefix: str, length: int) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:length].upper()}"


def create_application(form_data: dict) -> dict:
    form_data, now = form_data or {}, _now()
    application_id, ticket_id = _id("APP", 6), _id("TKT", 6)
    with _connect() as conn:
        conn.execute("INSERT INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            application_id, ticket_id, "Pending Review", now, now,
            form_data.get("ownerEmail") or form_data.get("owner_email"),
            form_data.get("businessLegalName") or form_data.get("business_legal_name"),
            str(form_data.get("loanAmount") or form_data.get("loan_amount") or ""),
            form_data.get("loanPurpose") or form_data.get("loan_purpose"), json.dumps(form_data), None, None))
    return {"application_id": application_id, "ticket_id": ticket_id, "status": "Pending Review"}


def _rows(sql: str, args: tuple = ()) -> list[dict]:
    with _connect() as conn:
        return [dict(row) for row in conn.execute(sql, args)]


def list_applications() -> list[dict]:
    return _rows("SELECT * FROM applications ORDER BY submitted_at DESC")


def list_customer_applications(email: str) -> list[dict]:
    return _rows("SELECT * FROM applications WHERE lower(owner_email)=lower(?) ORDER BY submitted_at DESC", (email,)) if email else []


def get_application(application_id: str) -> dict | None:
    rows = _rows("SELECT * FROM applications WHERE application_id=?", (application_id,))
    return rows[0] if rows else None


def upload_document(application_id: str, file_bytes: bytes, filename: str, content_type: str,
                    doc_type: str | None = None, uploaded_by: str | None = None) -> dict:
    if not get_application(application_id):
        raise RuntimeError("application not found")
    document_id, name = _id("DOC", 8), Path(filename).name
    path = _DOCS / f"{document_id}{Path(name).suffix}"
    path.write_bytes(file_bytes)
    row = (document_id, application_id, name, str(path), content_type or "application/octet-stream",
           len(file_bytes), doc_type, _now(), uploaded_by)
    with _connect() as conn:
        conn.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    return dict(zip(("document_id", "application_id", "filename", "local_path", "content_type", "size_bytes", "doc_type", "uploaded_at", "uploaded_by"), row))


def list_documents(application_id: str) -> list[dict]:
    return _rows("SELECT * FROM documents WHERE application_id=? ORDER BY uploaded_at DESC", (application_id,))


def get_local_document_path(document_id: str) -> Path | None:
    rows = _rows("SELECT local_path FROM documents WHERE document_id=?", (document_id,))
    path = Path(rows[0]["local_path"]) if rows else None
    return path if path and path.is_file() else None


def get_document_signed_url(application_id: str, document_id: str, expiration_minutes: int = 60) -> dict:
    document = next((d for d in list_documents(application_id) if d["document_id"] == document_id), None)
    if not document:
        raise RuntimeError("document not found")
    return {"document_id": document_id, "filename": document["filename"], "content_type": document["content_type"],
            "signed_url": f"/local-documents/{document_id}", "expires_in_minutes": expiration_minutes,
            "note": "Local development URL; Azure Blob SAS replaces this in Stage 2."}


def summarize_document(application_id: str, document_id: str) -> dict:
    document = next((d for d in list_documents(application_id) if d["document_id"] == document_id), None)
    if not document:
        raise RuntimeError("document not found")
    return {"document_id": document_id, "filename": document["filename"], "doc_type": document["doc_type"],
            "summary": "Local baseline: document stored successfully. Azure document extraction is added in Stage 2."}


def create_case(application_id: str, assigned_rm: str) -> dict:
    if not get_application(application_id):
        raise RuntimeError("application not found")
    case_id, now = _id("CASE", 8), _now()
    with _connect() as conn:
        conn.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)", (case_id, application_id, assigned_rm, "In Review", now, now))
    return {"case_id": case_id, "application_id": application_id, "assigned_rm": assigned_rm, "status": "In Review"}


def list_cases() -> list[dict]:
    return _rows("SELECT * FROM cases ORDER BY created_at DESC")


def get_case(case_id: str) -> dict | None:
    rows = _rows("SELECT * FROM cases WHERE case_id=? OR application_id=? ORDER BY created_at DESC", (case_id, case_id))
    return rows[0] if rows else None


def record_human_decision(case_id: str, decision: str, actor: str) -> str:
    decision = decision.upper()
    if decision not in {"APPROVED", "REJECTED"}:
        raise RuntimeError("decision must be APPROVED or REJECTED")
    case = get_case(case_id)
    now = _now()
    with _connect() as conn:
        if case:
            conn.execute("UPDATE cases SET status=?, updated_at=? WHERE case_id=?", (decision.title(), now, case_id))
            conn.execute("UPDATE applications SET status=?, updated_at=?, reviewed_by=? WHERE application_id=?", (decision.title(), now, actor, case["application_id"]))
        else:
            app_id = case_id.replace("CASE-", "APP-") if case_id.startswith("CASE-") else case_id
            conn.execute("INSERT OR REPLACE INTO cases VALUES (?, ?, ?, ?, ?, ?)", (case_id, app_id, actor, decision.title(), now, now))
            app_row = conn.execute("SELECT application_id FROM applications WHERE application_id=?", (app_id,)).fetchone()
            if not app_row:
                conn.execute(
                    "INSERT OR REPLACE INTO applications VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (app_id, f"TKT-{app_id.replace('APP-', '')}", decision.title(), now, now, "manager@loanprocessai.com", f"Commercial Applicant ({app_id})", "1500000", "Approved Commercial Facility", "{}", actor, "Manager approved.")
                )
            else:
                conn.execute("UPDATE applications SET status=?, updated_at=?, reviewed_by=? WHERE application_id=?", (decision.title(), now, actor, app_id))
        conn.execute("INSERT INTO case_audit_log VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4()), case_id, decision, actor, now))
    return f"Recorded {decision} decision for {case_id} by {actor}."


def _populate_state_dict(state: Any) -> None:
    if state.get("context_loaded"):
        return
    c_id = state.get("case_id")
    case = get_case(str(c_id)) if c_id else None
    application_id = state.get("application_id") or (case or {}).get("application_id")
    app_obj = get_application(str(application_id)) if application_id else {}
    state.update({
        "case": case or {},
        "application": app_obj or {},
        "application_id": application_id,
        "documents": list_documents(str(application_id)) if application_id else [],
        "context_loaded": True,
    })


def _hydrate_agent_outputs(state: dict, case_id: str | None) -> None:
    if not case_id:
        return
    for row in _rows("SELECT agent_name, output FROM agent_runs WHERE case_id=? AND status='completed' ORDER BY completed_at DESC", (case_id,)):
        mapping = _AGENTS.get(row["agent_name"])
        if mapping and not state.get(mapping[0]):
            text = json.loads(row["output"] or "{}").get("text", "")
            # Cap each upstream agent output in prompt state to prevent token overflow
            if len(text) > 3500:
                text = text[:3500] + "\n...[Summary continued in system records]..."
            state[mapping[0]] = text


def reset_case_runs(case_id: str) -> dict:
    """Purge old agent runs for a case and restore status to In Review."""
    with _connect() as conn:
        conn.execute("DELETE FROM agent_runs WHERE case_id=?", (case_id,))
        conn.execute("UPDATE cases SET status='In Review' WHERE case_id=?", (case_id,))
    return {"case_id": case_id, "status": "reset", "mode": "local"}


def build_initial_state(case_id: str, actor: str) -> dict:
    state = {"case_id": case_id, "actor": actor, "cases_list": [], "applications_list": [], "case": {}, "application": {}, "documents": []}
    state.update({value[0]: "" for value in _AGENTS.values()})
    state["chatbot_output"] = ""
    if case_id == "GENERAL" or case_id.startswith("ask:"):
        state.update({"cases_list": list_cases()[:10], "applications_list": list_applications()[:10]})
    _populate_state_dict(state)
    _hydrate_agent_outputs(state, case_id)
    return state


def load_case_context(callback_context: CallbackContext) -> None:
    """ADK before_agent_callback: hydrate state and log the agent's STARTED line."""
    state = callback_context.state
    _populate_state_dict(state)
    agent_name = _agent_name_from_context(callback_context)
    state[f"_started_mono::{agent_name}"] = time.monotonic()
    state[f"_started_iso::{agent_name}"] = _now()
    _log_event(agent_name, "STARTED", state.get("case_id"))


def make_start_callback(agent_name: str, output_key: str):
    """Return a before_agent_callback that logs STARTED and timestamps the run.

    The agent's own ``output_key`` is cleared here so a run that produces no
    text cannot inherit the previous run's output from the hydrated session
    state. Without this the old text would be persisted again (and returned by
    the API) as if the agent had just succeeded, which made failures silent.
    """

    def _start(callback_context: CallbackContext) -> None:
        state = callback_context.state
        state[f"_started_mono::{agent_name}"] = time.monotonic()
        state[f"_started_iso::{agent_name}"] = _now()
        state[f"{output_key}_started_at"] = _now()
        state[f"{output_key}_started_mono"] = state[f"_started_mono::{agent_name}"]
        state[output_key] = ""
        _log_event(agent_name, "STARTED", state.get("case_id"))

    return _start


def make_persist_callback(agent_name: str, output_key: str):
    def _persist(callback_context: CallbackContext) -> None:
        state = callback_context.state
        output = state.get(output_key)
        case_id = state.get("case_id")
        started_mono = (
            state.get(f"_started_mono::{agent_name}")
            or state.get(f"{output_key}_started_mono")
        )
        dur_ms = int((time.monotonic() - started_mono) * 1000) if started_mono else None
        now = _now()
        if not output:
            # Persist the failure so the run is visible in `agent_runs` too,
            # not only in the log file.
            try:
                with _connect() as conn:
                    conn.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (str(uuid.uuid4()), agent_name, case_id, state.get("application_id"),
                                  "failed", now, now, json.dumps({"text": ""}), "",
                                  "no_output_in_state"))
            except Exception as exc:  # noqa: BLE001
                _log_event(agent_name, "FAILED", case_id, dur_ms,
                           extra=f"error=persist_failed:{type(exc).__name__}")
                return
            _log_event(agent_name, "FAILED", case_id, dur_ms,
                       extra="error=no_output_in_state")
            return
        with _connect() as conn:
            conn.execute("INSERT INTO agent_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (str(uuid.uuid4()), agent_name, case_id, state.get("application_id"), "completed", now, now,
                          json.dumps({"text": str(output)}), str(output)[:1000], None))
        _log_event(agent_name, "COMPLETED", case_id, dur_ms,
                   extra=f"out_chars={len(str(output))}")
        # Telemetry hook: record real execution duration to Prometheus
        try:
            import sys
            app_mod = sys.modules.get("app")
            if app_mod:
                short_name = _AGENTS.get(agent_name, ("", agent_name.lower()))[1]
                dur_s = max(0.001, (dur_ms or 1000) / 1000.0)
                if hasattr(app_mod, "AGENT_STAGE_LATENCY_SECONDS"):
                    app_mod.AGENT_STAGE_LATENCY_SECONDS.labels(agent_name=short_name).set(dur_s)
                if hasattr(app_mod, "AGENT_EXECUTION_DURATION_SECONDS"):
                    app_mod.AGENT_EXECUTION_DURATION_SECONDS.labels(agent_name=short_name).observe(dur_s)
        except Exception:
            pass
    return _persist


def extract_document_text(file_path: Path | str, max_chars: int = 3500) -> str:
    """Extract readable text from a PDF, text, or json document on disk."""
    path = Path(file_path)
    if not path.is_file():
        return ""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            pages_text = []
            for i, page in enumerate(reader.pages):
                pt = page.extract_text() or ""
                if pt.strip():
                    pages_text.append(f"--- Page {i+1} ---\n{pt.strip()}")
            text = "\n\n".join(pages_text)
            if text.strip():
                return text[:max_chars]
        except Exception:
            pass
        # Fallback stream decompressor for PDFs
        try:
            import zlib
            import re
            data = path.read_bytes()
            streams = re.findall(b'stream[\r\n]+(.*?)[\r\n]+endstream', data, re.DOTALL)
            extracted = []
            for s in streams:
                try:
                    decomp = zlib.decompress(s).decode('latin1', errors='ignore')
                except Exception:
                    decomp = s.decode('latin1', errors='ignore')
                for tj in re.findall(r'\(((?:[^()\\]|\\.)*)\)\s*Tj', decomp):
                    extracted.append(tj)
                for arr in re.findall(r'\[(.*?)\]\s*TJ', decomp, re.DOTALL):
                    extracted.extend(re.findall(r'\(((?:[^()\\]|\\.)*)\)', arr))
            clean_text = ' '.join(extracted)
            clean_text = re.sub(r'\\([()\\])', r'\1', clean_text)
            if clean_text.strip():
                return clean_text[:max_chars]
        except Exception:
            pass
    elif suffix in (".txt", ".json", ".csv", ".md"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        except Exception:
            pass
    return ""


def make_attach_documents_callback(doc_type_prefixes: tuple[str, ...] | None = None, filename_keywords: tuple[str, ...] | None = None):
    """Attach document inventory and extracted readable text to the LLM request.

    Local/Azure baseline: extracts text from PDFs and documents on disk, so the
    agents (Intake, KYC, Financial Spreading) can read the actual identity fields,
    EIN certificate data, incorporation details, and financial statements.
    """
    def _attach(callback_context: CallbackContext, llm_request: LlmRequest):
        items = []
        for document in callback_context.state.get("documents") or []:
            doc_type = (document.get("doc_type") or "").lower()
            filename = (document.get("filename") or "").lower()
            matches = not doc_type_prefixes and not filename_keywords
            matches = matches or bool(doc_type_prefixes and any(doc_type.startswith(v) for v in doc_type_prefixes))
            matches = matches or bool(filename_keywords and any(v in filename for v in filename_keywords))
            if not matches:
                continue
            size = document.get("size_bytes")
            local_path = document.get("local_path")
            doc_text = extract_document_text(local_path) if local_path else ""
            meta_line = f"### Document: {document.get('filename')} | Type: {document.get('doc_type')} | ID: {document.get('document_id')} | Size: {size} bytes"
            if doc_text:
                items.append(f"{meta_line}\nExtracted Content:\n```\n{doc_text}\n```")
            else:
                items.append(f"{meta_line}\n(No text content extracted — metadata only)")
        if items:
            llm_request.contents.append(types.Content(role="user", parts=[types.Part(text=(
                "Attached Documents and Extracted Text Contents:\n\n" + "\n\n".join(items) + "\n\n"
                "Please analyze these documents and their extracted text to perform your evaluation."
            ))]))
        return None
    return _attach


def get_persisted_agent_outputs(case_id: str) -> dict:
    result = {value[1]: None for value in _AGENTS.values()}
    for row in _rows("SELECT agent_name, output FROM agent_runs WHERE (case_id=? OR application_id=?) AND status='completed' ORDER BY completed_at DESC", (case_id, case_id)):
        mapping = _AGENTS.get(row["agent_name"])
        if mapping and result[mapping[1]] is None:
            result[mapping[1]] = json.loads(row["output"] or "{}").get("text")
    return result


def flush_all_streaming_buffers() -> dict:
    return {"mode": "local", "message": "SQLite has no streaming buffer."}


def delete_application(application_id: str) -> dict:
    documents = list_documents(application_id)
    with _connect() as conn:
        cases = [row["case_id"] for row in conn.execute("SELECT case_id FROM cases WHERE application_id=?", (application_id,))]
        for case_id in cases:
            conn.execute("DELETE FROM agent_runs WHERE case_id=?", (case_id,))
            conn.execute("DELETE FROM case_audit_log WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM cases WHERE application_id=?", (application_id,))
        conn.execute("DELETE FROM documents WHERE application_id=?", (application_id,))
        conn.execute("DELETE FROM applications WHERE application_id=?", (application_id,))
    for document in documents:
        Path(document["local_path"]).unlink(missing_ok=True)
    return {"application_id": application_id, "documents_deleted": len(documents)}
