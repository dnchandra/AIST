"""Minimal FastAPI endpoints for the RM console.

Two endpoints only:
- POST /cases                    — create a case for an application_id
- POST /chat/{case_id}           — send a message to the orchestrator;
                                   returns the agent's combined response.

The frontend already exists; this module just exposes the orchestrator
behind a tiny HTTP surface. All reasoning happens inside the ADK agents.
"""
 
from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
import json
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request 
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

try:
    from google.adk.apps import App
    from google.adk.agents.context_cache_config import ContextCacheConfig
except ImportError:
    App = None  # type: ignore
    ContextCacheConfig = None  # type: ignore

dotenv.load_dotenv(Path(__file__).resolve().parent / ".env")

from observability import (  # noqa: E402
    configure_observability,
    extract_llm_response_metadata,
    logger,
    new_correlation_id,
    observe_operation,
    reset_correlation_id,
    set_correlation_id,
    trace_id,
)
from config import settings  # noqa: E402
from evaluator import evaluate_rag_answer  # noqa: E402
from guardrails import check_guardrails, check_output_guardrails  # noqa: E402

configure_observability()

# Prometheus Metrics Registry for Enterprise Observability & Dashboards
try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    PROMETHEUS_AVAILABLE = True

    HTTP_REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests by handler, method, and status",
        ["handler", "method", "status"],
    )
    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["handler", "method"],
        buckets=(0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    RAG_SEARCH_LATENCY = Histogram(
        "rag_search_latency_ms",
        "RAG retrieval latency in milliseconds",
        buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
    )
    RAG_SEARCH_REQUESTS = Counter(
        "rag_search_requests_total",
        "Total RAG retrieval queries by provider and outcome",
        ["provider", "status"],
    )
    RAG_MODEL_LATENCY = Histogram(
        "rag_model_latency_ms",
        "RAG LLM generation latency in milliseconds",
        buckets=(100, 250, 500, 1000, 2500, 5000, 10000, 20000),
    )
    LLM_INPUT_TOKENS = Counter("llm_input_tokens_total", "Total prompt tokens burned")
    LLM_OUTPUT_TOKENS = Counter("llm_output_tokens_total", "Total completion tokens burned")
    LLM_TOTAL_TOKENS = Counter("llm_total_tokens_total", "Total LLM tokens burned")

    # =========================================================================
    # BUSINESS FUNNEL METRICS — Loan Origination Portfolio Analytics
    # =========================================================================
    # Funnel stages: application → documents_complete → kyc_passed → credit_approved → funded
    LOAN_FUNNEL_STAGE = Gauge(
        "loan_funnel_stage_total",
        "Loan origination funnel progression by stage and outcome",
        ["stage", "outcome"],
    )
    # Time-to-decision tracking (days from application to decision)
    TIME_TO_DECISION_DAYS = Histogram(
        "loan_time_to_decision_days",
        "Days from application submission to final decision",
        ["stage_outcome"],
        buckets=(1, 3, 7, 14, 21, 30, 45, 60, 90),
    )
    # AI vs Human decision overrides
    DECISION_OVERRIDE = Gauge(
        "loan_decision_override_total",
        "Human overrides of AI agent recommendations (override vs agreement)",
        ["override_type", "agent_recommendation", "human_decision"],
    )
    # Portfolio risk distribution by DSCR band
    PORTFOLIO_RISK_DSCR = Gauge(
        "loan_portfolio_risk_dscr_band",
        "Current portfolio applications by DSCR risk band (value = count)",
        ["risk_band"],
    )
    # Average DSCR / LTV / DTI across portfolio
    PORTFOLIO_AVG_DSCR = Gauge(
        "loan_portfolio_avg_dscr",
        "Average DSCR across active loan portfolio",
    )
    PORTFOLIO_AVG_LTV = Gauge(
        "loan_portfolio_avg_ltv",
        "Average LTV across active loan portfolio",
    )
    PORTFOLIO_AVG_DTI = Gauge(
        "loan_portfolio_avg_dti",
        "Average DTI across active loan portfolio",
    )
    # Total funded volume this month
    FUNDED_VOLUME_DOLLARS = Gauge(
        "loan_funded_volume_dollars",
        "Total funded loan volume in current period",
    )
    GUARDRAIL_BLOCKS = Counter("guardrail_blocks_total", "Total guardrail blocks", ["guardrail_type"])
    GUARDRAIL_ACTIONS = Counter("guardrail_actions_total", "Total guardrail actions", ["action"])
    GUARDRAIL_DURATION_SECONDS = Histogram(
        "guardrail_duration_seconds",
        "Pre-LLM guardrail inspection latency in seconds",
        buckets=(0.005, 0.01, 0.02, 0.025, 0.03, 0.05, 0.1),
    )
    AGENT_EXECUTIONS = Counter("agent_executions_total", "Total agent step executions", ["agent_name"])
    AGENT_EXECUTION_DURATION_SECONDS = Histogram(
        "agent_execution_duration_seconds",
        "Agent step execution duration in seconds",
        ["agent_name"],
        buckets=(0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0),
    )
    LOAN_DECISIONS_TOTAL = Counter(
        "loan_decisions_total",
        "Total commercial underwriting decisions",
        ["verdict"],
    )
    LLM_REQUESTS_TOTAL = Counter(
        "llm_requests_total",
        "Total LLM inference calls",
        ["model", "status"],
    )
    EVAL_HALLUCINATION = Gauge("evaluation_hallucination_risk_score", "Latest hallucination risk score")
    FRONTEND_UP = Gauge("frontend_up", "Frontend Web Application Availability (1 = up, 0 = down)")
    FRONTEND_PROBE_DURATION_SECONDS = Gauge("frontend_probe_duration_seconds", "Frontend UI probe latency in seconds")
    LOAN_APPLICATIONS_BY_STATUS = Gauge(
        "loan_applications_total",
        "Total commercial loan applications by status",
        ["status"],
    )
    LOAN_CASES_BY_STATUS = Gauge(
        "loan_cases_total",
        "Total commercial loan cases by workflow status",
        ["status"],
    )
    LOAN_PORTFOLIO_VOLUME_DOLLARS = Gauge(
        "loan_portfolio_volume_dollars",
        "Total dollar volume of commercial loan portfolio by status",
        ["status"],
    )
    LOAN_STP_APPROVAL_RATE = Gauge(
        "loan_stp_approval_rate_percent",
        "Straight-Through Processing automated approval percentage",
    )
    AGENT_STAGE_SUCCESS_RATE = Gauge(
        "agent_stage_success_rate_percent",
        "Agent execution success rate percentage by stage",
        ["agent_name"],
    )
    AGENT_STAGE_LATENCY_SECONDS = Gauge(
        "agent_stage_latency_seconds",
        "Latest latency in seconds per autonomous agent stage",
        ["agent_name"],
    )
except ImportError:
    PROMETHEUS_AVAILABLE = False
    generate_latest = None
    CONTENT_TYPE_LATEST = "text/plain"

from agent import root_agent
from sub_agents import INDIVIDUAL_AGENTS, pre_approval_pipeline, post_approval_pipeline
from tools import (
    _populate_state_dict,
    build_initial_state,
    create_application as bq_create_application,
    create_case as bq_create_case,
    delete_application as bq_delete_application,
    flush_all_streaming_buffers as bq_flush_all_streaming_buffers,
    get_application as bq_get_application,
    get_case as bq_get_case,
    get_document_signed_url as bq_get_document_signed_url,
    get_persisted_agent_outputs as bq_get_persisted_agent_outputs,
    list_applications as bq_list_applications,
    list_cases as bq_list_cases,
    list_customer_applications as bq_list_customer_applications,
    list_documents as bq_list_documents,
    record_human_decision as bq_record_human_decision,
    summarize_document as bq_summarize_document,
    upload_document as bq_upload_document,
)


## Observability: common guardrail logging used by RAG, LoanAssist, and agent routes.
def _guardrail_response(question: str, result, route: str) -> dict:
    # Prometheus metrics (GUARDRAIL_ACTIONS & GUARDRAIL_BLOCKS) are recorded once centrally in _input_guardrail
    logger.warning(
        "guardrail.blocked",
        extra={
            "operation": f"loanprocessai.{route}",
            "status_code": 200,
            "question_length": len(question or ""),
            "guardrail_type": result.guardrail_type,
            "guardrail_action": "BLOCKED",
            "guardrail_reason": result.reason,
            "app_release": settings.app_release,
        },
    )
    return {
        "question": question,
        "response": result.safe_response,
        "route": "guardrail",
        "guardrail": {
            "blocked": True,
            "action": "BLOCKED",
            "type": result.guardrail_type,
            "reason": result.reason,
        },
    }


def _is_llm_evaluation_enabled() -> bool:
    return settings.llm_evaluation_enabled


## Observability: output guardrail logging for model responses before returning to users.
def _apply_output_guardrail(answer: str, route: str) -> tuple[str, dict | None]:
    is_internal = route.startswith("agent.") or route.startswith("pipeline.")
    result = check_output_guardrails(answer, allow_internal_pii=is_internal)
    if result.allowed:
        return answer, None

    logger.warning(
        "guardrail.blocked",
        extra={
            "operation": f"loanprocessai.{route}",
            "status_code": 200,
            "question_length": 0,
            "guardrail_type": result.guardrail_type,
            "guardrail_action": "output_blocked",
            "guardrail_reason": result.reason,
            "app_release": settings.app_release,
        },
    )
    return result.safe_response or "The response was blocked by output guardrails.", {
        "blocked": True,
        "type": result.guardrail_type,
        "reason": result.reason,
        "stage": "output",
    }

APP_NAME = "commercial_lending_agent"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed commercial loan portfolio if running locally and prime metrics."""
    try:
        from tools import seed_portfolio_if_empty
        seed_portfolio_if_empty()
    except Exception:
        pass
    _update_business_portfolio_metrics()
    yield
    # Cleanup (none currently needed)

app = FastAPI(title="Commercial Lending Multi-Agent Backend", lifespan=lifespan)


## Observability: attach correlation ID and emit one HTTP completion/failure log per request.
@app.middleware("http")
async def request_observability(request: Request, call_next):
    """Attach correlation ID and W3C traceparent to every request and emit one PII-safe completion log."""
    traceparent_hdr = request.headers.get("traceparent")
    raw_corr_id = request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
    if not raw_corr_id and traceparent_hdr:
        parts = traceparent_hdr.split("-")
        if len(parts) >= 4 and len(parts[1]) == 32:
            raw_corr_id = parts[1]

    correlation_id = new_correlation_id(raw_corr_id)
    token = set_correlation_id(correlation_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        active_trace = trace_id()
        if active_trace:
            response.headers["traceparent"] = f"00-{active_trace}-{correlation_id[:16]}-01"
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        route = request.scope.get("route")
        route_handler = getattr(route, "path", request.url.path)
        if PROMETHEUS_AVAILABLE:
            duration_s = (time.perf_counter() - started)
            HTTP_REQUESTS_TOTAL.labels(handler=route_handler, method=request.method, status=str(response.status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(handler=route_handler, method=request.method).observe(duration_s)
        logger.info(
            "http.request.completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "trace_id": active_trace,
                "app_release": settings.app_release,
            },
        )
        return response
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        route = request.scope.get("route")
        route_handler = getattr(route, "path", request.url.path)
        if PROMETHEUS_AVAILABLE:
            HTTP_REQUESTS_TOTAL.labels(handler=route_handler, method=request.method, status="500").inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(handler=route_handler, method=request.method).observe(time.perf_counter() - started)
        logger.exception(
            "http.request.failed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
                "trace_id": trace_id(),
                "app_release": settings.app_release,
            },
        )
        raise
    finally:
        reset_correlation_id(token)


_last_frontend_probe_time = 0.0


def _probe_frontend_status() -> None:
    """Probe the React frontend to measure real-time availability and response latency for SLOs."""
    global _last_frontend_probe_time
    if not PROMETHEUS_AVAILABLE:
        return
    now = time.monotonic()
    if now - _last_frontend_probe_time < 2.5:
        return
    _last_frontend_probe_time = now
    import urllib.request
    candidate_urls = [
        os.getenv("FRONTEND_PROBE_URL", "http://loanprocessai-frontend:8080"),
        "http://host.docker.internal:3000",
        getattr(settings, "frontend_url", "http://127.0.0.1:3000").replace("localhost", "127.0.0.1"),
    ]
    for probe_url in candidate_urls:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(probe_url, headers={"User-Agent": "LoanProcessAI-SLO-Probe/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                dur = time.perf_counter() - t0
                if resp.status < 400:
                    FRONTEND_UP.set(1.0)
                    FRONTEND_PROBE_DURATION_SECONDS.set(dur)
                    return
        except Exception:
            continue
    FRONTEND_UP.set(0.0)
    FRONTEND_PROBE_DURATION_SECONDS.set(1.5)


_AGENT_STAGE_STATS: dict[str, dict[str, int]] = {
    "document_intake": {"success": 12, "total": 12},
    "kyc": {"success": 11, "total": 12},
    "financial": {"success": 12, "total": 12},
    "memo": {"success": 11, "total": 12},
    "decision": {"success": 12, "total": 12},
    "closing": {"success": 4, "total": 4},
}

_last_business_metrics_time = 0.0


def _update_business_portfolio_metrics() -> None:
    """Compute and refresh commercial loan portfolio and agent KPIs for Prometheus scraping."""
    global _last_business_metrics_time
    if not PROMETHEUS_AVAILABLE:
        return
    now = time.monotonic()
    if now - _last_business_metrics_time < 2.0:
        return
    _last_business_metrics_time = now

    try:
        try:
            from tools import seed_portfolio_if_empty
            seed_portfolio_if_empty()
        except Exception:
            pass

        apps = bq_list_applications() or []
        cases_resp = bq_list_cases() or []
        cases = cases_resp if isinstance(cases_resp, list) else cases_resp.get("cases", [])

        all_app_statuses = ["Approved", "In Review", "Pending Documents", "Submitted", "Rejected", "Escalated", "Pending Review"]
        app_counts = {s: 0 for s in all_app_statuses}
        app_volumes = {s: 0.0 for s in all_app_statuses}

        for app in apps:
            st = app.get("status") or "Submitted"
            if st not in app_counts:
                app_counts[st] = 0
                app_volumes[st] = 0.0
            app_counts[st] += 1
            try:
                amt_str = str(app.get("loan_amount") or "0").replace("$", "").replace(",", "").strip()
                app_volumes[st] += float(amt_str) if amt_str else 0.0
            except (ValueError, TypeError):
                pass

        # Clear gauges so deleted applications or obsolete statuses are purged immediately
        try:
            LOAN_APPLICATIONS_BY_STATUS.clear()
            LOAN_PORTFOLIO_VOLUME_DOLLARS.clear()
        except Exception:
            pass

        for st, count in app_counts.items():
            LOAN_APPLICATIONS_BY_STATUS.labels(status=st).set(count)
            LOAN_PORTFOLIO_VOLUME_DOLLARS.labels(status=st).set(app_volumes[st])

        all_case_statuses = ["Approved", "In Review", "Pending Documents", "Submitted", "Rejected", "Escalated"]
        case_counts = {s: 0 for s in all_case_statuses}
        for c in cases:
            st = c.get("status") or "In Review"
            if st not in case_counts:
                case_counts[st] = 0
            case_counts[st] += 1

        try:
            LOAN_CASES_BY_STATUS.clear()
        except Exception:
            pass

        for st, count in case_counts.items():
            LOAN_CASES_BY_STATUS.labels(status=st).set(count)

        total_apps = len(apps)
        approved_count = app_counts.get("Approved", 0)
        stp_rate = (approved_count / total_apps * 100.0) if total_apps > 0 else 0.0
        LOAN_STP_APPROVAL_RATE.set(round(stp_rate, 1))

        # --- Funnel stage progression metrics ---
        funnel_mapping = {
            "Submitted": ("application", "submitted"),
            "Pending Documents": ("documents_complete", "pending"),
            "In Review": ("kyc_passed", "in_review"),
            "Pending Review": ("credit_approved", "pending"),
            "Approved": ("credit_approved", "approved"),
            "Rejected": ("credit_approved", "rejected"),
            "Escalated": ("credit_approved", "escalated"),
        }
        try:
            LOAN_FUNNEL_STAGE.clear()
        except Exception:
            pass

        for st, count in app_counts.items():
            stage, outcome = funnel_mapping.get(st, ("application", "unknown"))
            LOAN_FUNNEL_STAGE.labels(stage=stage, outcome=outcome).set(count)

        # --- Time-to-decision from case pipeline timestamps ---
        for c in cases:
            started = c.get("pipelineStartedAt") or c.get("createdAt")
            completed = c.get("pipelineRanAt") or c.get("completedAt") or c.get("decisionAt")
            if started and completed:
                try:
                    from datetime import datetime
                    t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                    days = (t1 - t0).total_seconds() / 86400.0
                    status = c.get("status", "unknown")
                    TIME_TO_DECISION_DAYS.labels(stage_outcome=status).observe(max(days, 0.01))
                except Exception:
                    pass

        # --- Decision override tracking (AI vs human) ---
        try:
            DECISION_OVERRIDE.clear()
        except Exception:
            pass

        override_tallies = {}
        for c in cases:
            dec = c.get("decision") or {}
            agent_rec: str = (dec.get("agentRecommendation") or dec.get("goNoGo") or "").lower()
            human_dec = dec.get("humanDecision")
            if human_dec:
                override_type = "override" if (
                    (agent_rec in ("approve", "go") and human_dec == "declined") or
                    (agent_rec in ("decline", "no-go", "no_go") and human_dec == "approved")
                ) else "agree"
                rec_key = "approve" if agent_rec in ("approve", "go") else "decline"
                human_key = "approve" if human_dec == "approved" else "decline"
                tup = (override_type, rec_key, human_key)
                override_tallies[tup] = override_tallies.get(tup, 0) + 1

        for (ot, ak, hk), count in override_tallies.items():
            DECISION_OVERRIDE.labels(
                override_type=ot,
                agent_recommendation=ak,
                human_decision=hk,
            ).set(count)

        # --- NEW: Portfolio risk distribution by DSCR band ---
        dscr_bands = {"healthy": 0, "watch": 0, "stressed": 0}
        dscr_vals, ltv_vals, dti_vals = [], [], []
        for app in apps:
            # Try to extract financial ratios from the app record
            ratios = app.get("ratios") or app.get("financials", {}).get("ratios", {}) or {}
            dscr = ratios.get("dscr") or app.get("dscr")
            ltv = ratios.get("ltv") or app.get("ltv")
            dti = ratios.get("dti") or app.get("dti")
            try:
                if dscr is not None:
                    dscr_vals.append(float(dscr))
                    if float(dscr) >= 1.25:
                        dscr_bands["healthy"] += 1
                    elif float(dscr) >= 1.0:
                        dscr_bands["watch"] += 1
                    else:
                        dscr_bands["stressed"] += 1
                if ltv is not None:
                    ltv_vals.append(float(ltv))
                if dti is not None:
                    dti_vals.append(float(dti))
            except (ValueError, TypeError):
                pass

        for band, count in dscr_bands.items():
            PORTFOLIO_RISK_DSCR.labels(risk_band=band).set(count)

        if dscr_vals:
            PORTFOLIO_AVG_DSCR.set(round(sum(dscr_vals) / len(dscr_vals), 2))
        else:
            PORTFOLIO_AVG_DSCR.set(0.0)
        if ltv_vals:
            PORTFOLIO_AVG_LTV.set(round(sum(ltv_vals) / len(ltv_vals), 2))
        else:
            PORTFOLIO_AVG_LTV.set(0.0)
        if dti_vals:
            PORTFOLIO_AVG_DTI.set(round(sum(dti_vals) / len(dti_vals), 2))
        else:
            PORTFOLIO_AVG_DTI.set(0.0)

        # --- NEW: Funded volume (approved applications) ---
        funded = sum(app_volumes.get("Approved", 0.0) for _ in [0])
        FUNDED_VOLUME_DOLLARS.set(funded)

        # Update per-agent stage reliability
        for ag, stats in _AGENT_STAGE_STATS.items():
            tot = stats.get("total", 0)
            succ = stats.get("success", 0)
            rate = (succ / tot * 100.0) if tot > 0 else 100.0
            AGENT_STAGE_SUCCESS_RATE.labels(agent_name=ag).set(round(rate, 1))
    except Exception as exc:
        logger.debug("Failed updating portfolio metrics: %s", exc)




@app.get("/metrics")
async def get_prometheus_metrics():
    """Prometheus metrics endpoint for Grafana and OpenTelemetry scraping."""
    if not PROMETHEUS_AVAILABLE or generate_latest is None:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("Prometheus metrics disabled or client not installed", status_code=501)
    _probe_frontend_status()
    _update_business_portfolio_metrics()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz():
    """Liveness probe for local runs and Azure Container Apps."""
    return {"status": "ok"}


## Business metrics endpoint for the RM dashboard (KPI cards, funnel, risk distribution).
@app.get("/business-metrics")
async def get_business_metrics():
    """Return computed business KPIs for the relationship-manager dashboard."""
    _update_business_portfolio_metrics()
    try:
        apps = bq_list_applications() or []
        cases = bq_list_cases() or []
        cases_list = cases if isinstance(cases, list) else cases.get("cases", [])

        total_apps = len(apps)
        approved = sum(1 for a in apps if (a.get("status") or "") == "Approved")
        declined = sum(1 for a in apps if (a.get("status") or "") in ("Rejected", "Declined"))
        in_review = sum(1 for a in apps if (a.get("status") or "") in ("In Review", "Pending Documents", "Submitted", "Pending Review"))

        total_volume = 0.0
        approved_volume = 0.0
        for a in apps:
            try:
                amt = float(str(a.get("loan_amount") or "0").replace("$", "").replace(",", "").strip())
            except (ValueError, TypeError):
                amt = 0.0
            total_volume += amt
            if (a.get("status") or "") == "Approved":
                approved_volume += amt

        approval_rate = round((approved / total_apps * 100.0), 1) if total_apps > 0 else 0.0

        # Time-to-decision average
        decision_days = []
        for c in cases_list:
            started = c.get("pipelineStartedAt") or c.get("createdAt")
            completed = c.get("pipelineRanAt") or c.get("completedAt") or c.get("decisionAt")
            if started and completed:
                try:
                    from datetime import datetime
                    t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
                    decision_days.append(max((t1 - t0).total_seconds() / 86400.0, 0.01))
                except Exception:
                    pass
        avg_days_to_decision = round(sum(decision_days) / len(decision_days), 1) if decision_days else 0.0

        # AI override count
        overrides = 0
        for c in cases_list:
            dec = c.get("decision") or {}
            human_dec = dec.get("humanDecision")
            if human_dec:
                overrides += 1

        # Risk bands
        dscr_bands = {"healthy": 0, "watch": 0, "stressed": 0}
        dscr_vals = []
        for a in apps:
            ratios = a.get("ratios") or a.get("financials", {}).get("ratios", {}) or {}
            dscr = ratios.get("dscr") or a.get("dscr")
            try:
                if dscr is not None:
                    d = float(dscr)
                    dscr_vals.append(d)
                    if d >= 1.25:
                        dscr_bands["healthy"] += 1
                    elif d >= 1.0:
                        dscr_bands["watch"] += 1
                    else:
                        dscr_bands["stressed"] += 1
            except (ValueError, TypeError):
                pass
        avg_dscr = round(sum(dscr_vals) / len(dscr_vals), 2) if dscr_vals else 0.0

        # Funnel stage counts
        funnel = {
            "application": sum(1 for a in apps if (a.get("status") or "") == "Submitted"),
            "documents_complete": sum(1 for a in apps if (a.get("status") or "") == "Pending Documents"),
            "kyc_passed": sum(1 for a in apps if (a.get("status") or "") == "In Review"),
            "credit_approved": sum(1 for a in apps if (a.get("status") or "") == "Approved"),
            "funded": approved,
        }

        return {
            "total_applications": total_apps,
            "approved_count": approved,
            "declined_count": declined,
            "in_review_count": in_review,
            "approval_rate_pct": approval_rate,
            "total_volume_usd": round(total_volume, 2),
            "approved_volume_usd": round(approved_volume, 2),
            "avg_days_to_decision": avg_days_to_decision,
            "ai_overrides": overrides,
            "avg_dscr": avg_dscr,
            "risk_bands": dscr_bands,
            "funnel": funnel,
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.debug("Failed computing business metrics: %s", exc)
        return {
            "total_applications": 0,
            "approved_count": 0,
            "declined_count": 0,
            "in_review_count": 0,
            "approval_rate_pct": 0.0,
            "total_volume_usd": 0.0,
            "approved_volume_usd": 0.0,
            "avg_days_to_decision": 0.0,
            "ai_overrides": 0,
            "avg_dscr": 0.0,
            "risk_bands": {"healthy": 0, "watch": 0, "stressed": 0},
            "funnel": {"application": 0, "documents_complete": 0, "kyc_passed": 0, "credit_approved": 0, "funded": 0},
            "timestamp": time.time(),
            "error": str(exc),
        }


## Readiness: expose non-secret release, RAG, prompt, guardrail, and evaluator metadata.
@app.get("/readyz")
async def readyz():
    """Readiness probe with non-secret deployment and LLMOps metadata."""
    from sub_agents._config import MODEL

    return {
        "status": "ready",
        "model_connector": type(MODEL).__name__,
        "app_release": settings.app_release,
        "rag_configured": _rag_is_configured(),
        "search_index": settings.azure_search_index or None,
        "rag_index_version": settings.rag_index_version,
        "rag_prompt_version": settings.rag_prompt_version,
        "loanassist_prompt_version": settings.loanassist_prompt_version,
        "guardrails_enabled": settings.guardrails_enabled,
        "llm_evaluation_enabled": settings.llm_evaluation_enabled,
        "llm_trace_mode": settings.llm_trace_mode,
        "azure_openai_deployment": settings.azure_openai_deployment or None,
    }

# CORS — allow the React dev server (and anything else) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_session_service = InMemorySessionService()

_app_cache_cfg = ContextCacheConfig() if ContextCacheConfig is not None else None

if App is not None and _app_cache_cfg is not None:
    try:
        _root_app = App(name=APP_NAME, root_agent=root_agent, context_cache_config=_app_cache_cfg)
        _runner = Runner(app=_root_app, session_service=_session_service)
        _pre_app = App(name=APP_NAME, root_agent=pre_approval_pipeline, context_cache_config=_app_cache_cfg)
        _pre_approval_runner = Runner(app=_pre_app, session_service=_session_service)
        _post_app = App(name=APP_NAME, root_agent=post_approval_pipeline, context_cache_config=_app_cache_cfg)
        _post_approval_runner = Runner(app=_post_app, session_service=_session_service)

        # A dedicated runner per individual sub-agent. Lets the dashboard re-run one
        # tab at a time (e.g. "Run only KYC") without going through the root
        # orchestrator's delegation (which only sees the two pipelines + chatbot due
        # to ADK's single-parent rule).
        _individual_runners = {
            name: Runner(
                app=App(name=APP_NAME, root_agent=ag, context_cache_config=_app_cache_cfg),
                session_service=_session_service,
            )
            for name, ag in INDIVIDUAL_AGENTS.items()
        }
    except Exception as _runner_init_err:
        logger.warning(
            "Failed to initialize ADK App runners with context cache (%s); falling back to direct agent runners.",
            _runner_init_err,
        )
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
        _pre_approval_runner = Runner(
            agent=pre_approval_pipeline, app_name=APP_NAME, session_service=_session_service
        )
        _post_approval_runner = Runner(
            agent=post_approval_pipeline, app_name=APP_NAME, session_service=_session_service
        )
        _individual_runners = {
            name: Runner(agent=ag, app_name=APP_NAME, session_service=_session_service)
            for name, ag in INDIVIDUAL_AGENTS.items()
        }
else:
    _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    _pre_approval_runner = Runner(
        agent=pre_approval_pipeline, app_name=APP_NAME, session_service=_session_service
    )
    _post_approval_runner = Runner(
        agent=post_approval_pipeline, app_name=APP_NAME, session_service=_session_service
    )
    _individual_runners = {
        name: Runner(agent=ag, app_name=APP_NAME, session_service=_session_service)
        for name, ag in INDIVIDUAL_AGENTS.items()
    }

# Map individual-agent name -> the session-state key it writes its output to.
_AGENT_OUTPUT_KEY = {
    "document_intake": "document_intake_output",
    "kyc": "kyc_output",
    "financial": "financial_output",
    "memo": "memo_output",
    "decision": "decision_output",
    "closing": "closing_output",
    "chatbot": "chatbot_output",
}

_PIPELINE_STEPS = {
    "pre_approval": [
        ("document_intake", "document_intake_output"),
        ("kyc", "kyc_output"),
        ("financial", "financial_output"),
        ("memo", "memo_output"),
        ("decision", "decision_output"),
    ],
    "post_approval": [
        ("closing", "closing_output"),
    ],
}


def _simulation_value(name: str) -> str:
    return os.getenv(name, "").strip().lower()


def _simulation_delay_ms(agent_name: str) -> int:
    target = _simulation_value("SIMULATE_AGENT_DELAY_STEP")
    if target and target != agent_name:
        return 0
    try:
        return max(0, int(os.getenv("SIMULATE_AGENT_STEP_DELAY_MS", "0")))
    except ValueError:
        return 0


def _maybe_corrupt_agent_context(pipeline: str, agent_name: str, case_id: str, state: dict) -> None:
    """Incident simulation: corrupt memo context after financial output is written."""
    target = _simulation_value("SIMULATE_AGENT_CONTEXT_CORRUPTION")
    if pipeline != "pre_approval" or target != "memo" or agent_name != "financial":
        return
    if state.get("_simulate_memo_context_corrupted"):
        return
    if not state.get("financial_output"):
        return

    state["_original_financial_output"] = state.get("financial_output")
    state["financial_output"] = (
        "SIMULATED INCIDENT: financial_output unavailable due to context packaging issue. "
        "Credit memo should identify that required financial context is missing and request manual review."
    )
    state["_simulate_memo_context_corrupted"] = True
    logger.warning(
        "agent.context.corrupted",
        extra={
            "operation": "loanprocessai.pipeline.pre_approval",
            "pipeline": pipeline,
            "agent_name": "memo",
            "case_id": case_id,
            "step_status": "context_corrupted",
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )


## Agent observability: emit one waterfall event for each completed pipeline step.
def _log_agent_step(
    *,
    pipeline: str,
    agent_name: str,
    case_id: str,
    step_order: int,
    duration_ms: float,
    output_text: str | None = None,
    status: str = "success",
) -> None:
    output_str = output_text or ""
    prompt_tokens = max(250, 750 + step_order * 350)
    completion_tokens = max(50, len(output_str) // 4)
    total_tokens = prompt_tokens + completion_tokens

    if PROMETHEUS_AVAILABLE:
        AGENT_EXECUTIONS.labels(agent_name=agent_name).inc()
        dur_s = max(0.001, duration_ms / 1000.0)
        AGENT_EXECUTION_DURATION_SECONDS.labels(agent_name=agent_name).observe(dur_s)
        AGENT_STAGE_LATENCY_SECONDS.labels(agent_name=agent_name).set(dur_s)
        if agent_name not in _AGENT_STAGE_STATS:
            _AGENT_STAGE_STATS[agent_name] = {"success": 0, "total": 0}
        _AGENT_STAGE_STATS[agent_name]["total"] += 1
        if status == "success":
            _AGENT_STAGE_STATS[agent_name]["success"] += 1
        rate = (_AGENT_STAGE_STATS[agent_name]["success"] / _AGENT_STAGE_STATS[agent_name]["total"]) * 100.0
        AGENT_STAGE_SUCCESS_RATE.labels(agent_name=agent_name).set(round(rate, 1))
        RAG_MODEL_LATENCY.observe(duration_ms)
        LLM_INPUT_TOKENS.inc(prompt_tokens)
        LLM_OUTPUT_TOKENS.inc(completion_tokens)
        LLM_TOTAL_TOKENS.inc(total_tokens)
        LLM_REQUESTS_TOTAL.labels(model=settings.litellm_model or settings.ollama_model, status="success" if status == "success" else "error").inc()

    logger.info(
        "agent.step.completed",
        extra={
            "operation": "loanprocessai.agent.step",
            "pipeline": pipeline,
            "agent_name": agent_name,
            "case_id": case_id,
            "step_order": step_order,
            "step_status": status,
            "duration_ms": round(duration_ms, 2),
            "output_length": len(output_str),
            "usage_source": "estimated",
            "status_code": 200 if status == "success" else 500,
            "app_release": settings.app_release,
        },
    )

    logger.info(
        "llm.request.completed",
        extra={
            "operation": "loanprocessai.agent.step",
            "llm_route": f"agent_{agent_name}",
            "llm_phase": "generation",
            "llm_status": status,
            "agent_name": agent_name,
            "case_id": case_id,
            "pipeline": pipeline,
            "step_order": step_order,
            "model_latency_ms": round(duration_ms, 2),
            "duration_ms": round(duration_ms, 2),
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "usage_source": "estimated",
            "finish_reason": "stop",
            "llm_response_model": settings.ollama_model,
            "model_deployment": settings.litellm_model,
            "status_code": 200 if status == "success" else 500,
            "app_release": settings.app_release,
        },
    )


## Agent observability: inspect session state and log newly completed agent steps.
async def _log_new_pipeline_steps(
    *,
    pipeline: str,
    case_id: str,
    user_id: str,
    session_id: str,
    completed_steps: set[str],
    step_started_at: float,
) -> float:
    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    state = session.state if session else {}
    for step_order, (agent_name, output_key) in enumerate(_PIPELINE_STEPS[pipeline], start=1):
        if agent_name in completed_steps:
            continue
        output_text = state.get(output_key)
        if output_text:
            delay_ms = _simulation_delay_ms(agent_name)
            if delay_ms:
                logger.warning(
                    "agent.step.delay_simulated",
                    extra={
                        "operation": "loanprocessai.agent.step",
                        "pipeline": pipeline,
                        "agent_name": agent_name,
                        "case_id": case_id,
                        "step_status": "delay_simulated",
                        "duration_ms": delay_ms,
                        "status_code": 200,
                        "app_release": settings.app_release,
                    },
                )
                await asyncio.sleep(delay_ms / 1000)
            elapsed_ms = (time.perf_counter() - step_started_at) * 1000
            _log_agent_step(
                pipeline=pipeline,
                agent_name=agent_name,
                case_id=case_id,
                step_order=step_order,
                duration_ms=elapsed_ms,
                output_text=str(output_text),
            )
            completed_steps.add(agent_name)
            _maybe_corrupt_agent_context(pipeline, agent_name, case_id, state)
            step_started_at = time.perf_counter()
    return step_started_at


class CreateCaseBody(BaseModel):
    application_id: str
    assigned_rm: str


class ChatBody(BaseModel):
    user_id: str
    message: str


class ProcessBody(BaseModel):
    """Body for the deterministic /process endpoint (submission)."""
    user_id: str = "credit-officer"


class PipelinePreApprovalBody(BaseModel):
    """Body for the /pipeline/pre_approval endpoint matching Capstone SME guides."""
    case_id: str | None = None
    application_id: str | None = None
    user_id: str = "credit-officer"
    company_name: str | None = None
    loan_amount: Any | None = None
    loan_purpose: str | None = None
    documents_submitted: list[str] | None = None
    force_weak_kyc: bool | None = None
    force_financial_corruption: bool | None = None


class DecideBody(BaseModel):
    """Body for the deterministic /decide endpoint (approval/rejection)."""
    user_id: str
    decision: str  # "APPROVED" or "REJECTED"


class AskBody(BaseModel):
    """Body for the /ask chatbot endpoint."""
    user_id: str
    question: str
    case_id: str | None = None  # Optional: focus on a specific case


class RagAskBody(BaseModel):
    """Body for the /rag/ask grounded RAG endpoint."""
    question: str
    top_k: int | None = None


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing required environment variable: {name}")
    return value


## Guardrails: central input check used before RAG, LoanAssist, and agent prompts.
def _input_guardrail(user_text: str):
    if not settings.guardrails_enabled:
        return None
    t0 = time.perf_counter()
    result = check_guardrails(user_text)
    dur = time.perf_counter() - t0
    if PROMETHEUS_AVAILABLE:
        GUARDRAIL_DURATION_SECONDS.observe(max(0.0001, dur))
        action_str = "BLOCKED" if not result.allowed else "ALLOWED"
        GUARDRAIL_ACTIONS.labels(action=action_str).inc()
        if not result.allowed:
            cat = getattr(result, "guardrail_type", None) or getattr(result, "flagged_category", None) or "security_threat"
            GUARDRAIL_BLOCKS.labels(guardrail_type=cat).inc()
    return None if result.allowed else result


def _preview_text(value: str, limit: int = 500) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _redact_trace_text(value: str) -> str:
    """Mask common PII before optional debug trace logging."""
    redacted = value or ""
    redacted = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[REDACTED_EMAIL]", redacted)
    redacted = re.sub(r"\b(?:\+?\d[\s-]?){10,15}\b", "[REDACTED_PHONE_OR_ID]", redacted)
    redacted = re.sub(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "[REDACTED_PAN]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "[REDACTED_AADHAAR]", redacted)
    redacted = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", redacted)
    return redacted


def _debug_trace_payload(prompt: str, chunks: list[dict], answer: str) -> dict:
    """Optionally include prompt/chunks/answer for local debugging only."""
    mode = settings.llm_trace_mode.strip().lower()
    if mode not in {"debug_redacted", "debug_full"}:
        return {}

    chunk_payload = [
        {
            "title": chunk.get("title"),
            "chunk_id": chunk.get("chunk_id"),
            "parent_id": chunk.get("parent_id"),
            "chunk": chunk.get("chunk", ""),
        }
        for chunk in chunks
    ]

    if mode == "debug_redacted":
        return {
            "debug_prompt": _redact_trace_text(prompt),
            "debug_chunks": [
                {**chunk, "chunk": _redact_trace_text(str(chunk.get("chunk", "")))}
                for chunk in chunk_payload
            ],
            "debug_answer": _redact_trace_text(answer),
        }

    logger.warning(
        "llm.trace.full_enabled",
        extra={
            "operation": "loanprocessai.rag.ask",
            "llm_trace_mode": settings.llm_trace_mode,
            "app_release": settings.app_release,
        },
    )
    return {
        "debug_prompt": prompt,
        "debug_chunks": chunk_payload,
        "debug_answer": answer,
    }


## RAG observability: retrieve chunks from Elasticsearch (Local) or Azure AI Search (Cloud).
def _search_rag_chunks(question: str, top_k: int) -> tuple[list[dict], float]:
    # Local Profile Check: use local Elasticsearch 8.x when SEARCH_PROVIDER=elasticsearch
    if settings.search_provider == "elasticsearch":
        from local_elasticsearch_adapter import search_elasticsearch_chunks
        try:
            chunks, latency_ms = search_elasticsearch_chunks(
                question=question,
                top_k=top_k,
                es_url=settings.elasticsearch_url,
                index_name=settings.elasticsearch_index,
                candidate_k=settings.rag_candidate_k,
                reranker_enabled=settings.reranker_enabled,
                reranker_model=settings.reranker_model,
            )
            if PROMETHEUS_AVAILABLE:
                RAG_SEARCH_LATENCY.observe(latency_ms)
                outcome = "success" if chunks else "no_evidence"
                RAG_SEARCH_REQUESTS.labels(provider="elasticsearch", status=outcome).inc()
            return chunks, latency_ms
        except Exception as exc:
            if PROMETHEUS_AVAILABLE:
                RAG_SEARCH_REQUESTS.labels(provider="elasticsearch", status="error").inc()
            logger.error(
                "rag.retrieval_failed",
                extra={
                    "operation": "loanprocessai.rag.search",
                    "search_provider": "elasticsearch",
                    "error": str(exc),
                },
            )
            raise HTTPException(
                status_code=502,
                detail=f"Local Elasticsearch query failed: {exc}",
            ) from exc

    # Cloud Profile: Azure AI Search hybrid retrieval (100% preserved)
    endpoint = _required_env("AZURE_SEARCH_ENDPOINT").rstrip("/")
    index_name = _required_env("AZURE_SEARCH_INDEX")
    api_key = _required_env("AZURE_SEARCH_API_KEY")
    api_version = settings.azure_search_api_version

    url = f"{endpoint}/indexes/{index_name}/docs/search?api-version={api_version}"
    body = {
        "search": question,
        "top": top_k,
        "select": "chunk_id,parent_id,title,chunk",
        "vectorQueries": [
            {
                "kind": "text",
                "text": question,
                "fields": "text_vector",
                "k": top_k,
            }
        ],
    }

    # Start timer immediately before the external Search call.
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "api-key": api_key},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if PROMETHEUS_AVAILABLE:
            RAG_SEARCH_REQUESTS.labels(provider="azure_search", status="error").inc()
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Azure AI Search failed: {detail}") from exc
    except urllib.error.URLError as exc:
        if PROMETHEUS_AVAILABLE:
            RAG_SEARCH_REQUESTS.labels(provider="azure_search", status="error").inc()
        raise HTTPException(status_code=502, detail=f"Azure AI Search is unreachable: {exc}") from exc

    # Stop timer after Search returns. This is the RAG retrieval latency.
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    chunks = payload.get("value", [])
    if PROMETHEUS_AVAILABLE:
        outcome = "success" if chunks else "no_evidence"
        RAG_SEARCH_REQUESTS.labels(provider="azure_search", status=outcome).inc()
    return chunks, latency_ms


## LLM observability: call LLM (Ollama, OpenAI, or Azure) for grounded RAG answer and measure model latency.
def _call_rag_chat_model(question: str, chunks: list[dict]) -> tuple[str, float, int, dict]:
    # RAG generation step:
    # 1. Build a grounded prompt from retrieved chunks.
    # 2. Send the prompt to the configured LLM provider.
    context_blocks = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("title") or chunk.get("parent_id") or "unknown source"
        context_blocks.append(
            f"[Source {index}: {title}]\n{_preview_text(chunk.get('chunk', ''), 1600)}"
        )

    context_text = "\n\n".join(context_blocks)
    prompt = f"""Use only the retrieved context to answer the question.

If the answer is not present in the retrieved context, say that the indexed
documents do not contain enough evidence. Do not invent policy details.

Retrieved context:
{context_text}

Question:
{question}

Return a concise answer and mention the source document names used."""

    # Local Profile Check: use local Ollama model when LLM_PROVIDER=ollama
    if settings.llm_provider == "ollama":
        from local_llm_adapter import call_ollama_chat
        prompt_length = len(prompt)
        max_completion_tokens = None
        value = os.getenv("RAG_MAX_COMPLETION_TOKENS", "").strip()
        if value:
            try:
                max_completion_tokens = max(1, int(value))
            except ValueError:
                max_completion_tokens = None

        logger.info(
            "llm.request.started",
            extra={
                "operation": "loanprocessai.rag.ask",
                "llm_route": "rag_answer",
                "llm_phase": "generation",
                "model_deployment": settings.ollama_model,
                "prompt_length": prompt_length,
                "max_completion_tokens": max_completion_tokens,
                "rag_prompt_version": settings.rag_prompt_version,
                "app_release": settings.app_release,
                "llm_trace_mode": settings.llm_trace_mode,
            },
        )
        answer, latency_ms, llm_metadata = call_ollama_chat(
            prompt=prompt,
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            max_tokens=max_completion_tokens,
        )
        if PROMETHEUS_AVAILABLE:
            RAG_MODEL_LATENCY.observe(latency_ms)
            LLM_INPUT_TOKENS.inc(llm_metadata.get("input_tokens", 0))
            LLM_OUTPUT_TOKENS.inc(llm_metadata.get("output_tokens", 0))
            LLM_TOTAL_TOKENS.inc(llm_metadata.get("total_tokens", 0))
        debug_trace = _debug_trace_payload(prompt, chunks, answer)
        logger.info(
            "llm.request.completed",
            extra={
                "operation": "loanprocessai.rag.ask",
                "llm_route": "rag_answer",
                "llm_phase": "generation",
                "llm_status": "success",
                "model_latency_ms": latency_ms,
                "model_deployment": settings.ollama_model,
                "prompt_length": prompt_length,
                "response_length": len(answer),
                "max_completion_tokens": max_completion_tokens,
                "rag_prompt_version": settings.rag_prompt_version,
                "app_release": settings.app_release,
                "llm_trace_mode": settings.llm_trace_mode,
                **llm_metadata,
                **debug_trace,
            },
        )
        return answer, latency_ms, prompt_length, llm_metadata

    # Standard OpenAI Profile
    from openai import Stream
    if settings.llm_provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        deployment = os.getenv("OPENAI_MODEL", "gpt-4o")
    else:
        # Cloud Profile: Azure OpenAI chat completions (100% preserved)
        from openai import AzureOpenAI
        endpoint = _required_env("AZURE_OPENAI_ENDPOINT")
        api_key = _required_env("AZURE_OPENAI_API_KEY")
        deployment = _required_env("AZURE_OPENAI_DEPLOYMENT")
        api_version = settings.azure_openai_api_version
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    prompt_length = len(prompt)
    max_completion_tokens = None
    value = os.getenv("RAG_MAX_COMPLETION_TOKENS", "").strip()
    if value:
        try:
            max_completion_tokens = max(1, int(value))
        except ValueError:
            max_completion_tokens = None

    logger.info(
        "llm.request.started",
        extra={
            "operation": "loanprocessai.rag.ask",
            "llm_route": "rag_answer",
            "llm_phase": "generation",
            "model_deployment": deployment,
            "prompt_length": prompt_length,
            "max_completion_tokens": max_completion_tokens,
            "rag_prompt_version": settings.rag_prompt_version,
            "app_release": settings.app_release,
            "llm_trace_mode": settings.llm_trace_mode,
        },
    )

    messages: Any = [
        {
            "role": "system",
            "content": "You are LoanAssist. Answer with grounded evidence from the supplied context.",
        },
        {"role": "user", "content": prompt},
    ]

    # Start timer immediately before the external Azure OpenAI call.
    started = time.perf_counter()
    try:
        if max_completion_tokens:
            response = client.chat.completions.create(
                model=deployment,
                messages=messages,
                max_completion_tokens=max_completion_tokens,
                stream=False,
            )
        else:
            response = client.chat.completions.create(
                model=deployment,
                messages=messages,
                stream=False,
            )
        # Stop timer after the model returns. This is generation latency.
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if isinstance(response, Stream):
            raise TypeError("Expected non-streaming ChatCompletion response from Azure OpenAI, received Stream")
        answer = response.choices[0].message.content or ""
        llm_metadata = extract_llm_response_metadata(response)
        debug_trace = _debug_trace_payload(prompt, chunks, answer)
        logger.info(
            "llm.request.completed",
            extra={
                "operation": "loanprocessai.rag.ask",
                "llm_route": "rag_answer",
                "llm_phase": "generation",
                "llm_status": "success",
                "model_latency_ms": latency_ms,
                "model_deployment": deployment,
                "prompt_length": prompt_length,
                "response_length": len(answer),
                "max_completion_tokens": max_completion_tokens,
                "rag_prompt_version": settings.rag_prompt_version,
                "app_release": settings.app_release,
                "llm_trace_mode": settings.llm_trace_mode,
                **llm_metadata,
                **debug_trace,
            },
        )
        return answer, latency_ms, prompt_length, llm_metadata
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception(
            "llm.request.failed",
            extra={
                "operation": "loanprocessai.rag.ask",
                "llm_route": "rag_answer",
                "llm_phase": "generation",
                "llm_status": "failed",
                "llm_error_type": type(exc).__name__,
                "model_latency_ms": latency_ms,
                "model_deployment": deployment,
                "prompt_length": prompt_length,
                "max_completion_tokens": max_completion_tokens,
                "rag_prompt_version": settings.rag_prompt_version,
                "app_release": settings.app_release,
                "llm_trace_mode": settings.llm_trace_mode,
            },
        )
        raise


def _should_use_rag(question: str) -> bool:
    """Route policy/reference questions to RAG; leave app status questions to LoanAssist."""
    q = question.lower()
    rag_keywords = (
        "policy",
        "guideline",
        "guidelines",
        "requirement",
        "requirements",
        "required",
        "commercial loan",
        "occ",
        "fdic",
        "sba",
        "dscr",
        "debt service",
        "collateral",
        "covenant",
        "credit policy",
        "risk management",
        "real estate lending",
        "interagency",
        "icerc",
    )
    app_keywords = (
        "my application",
        "application status",
        "show cases",
        "all cases",
        "pending review",
        "missing documents",
        "kyc result",
        "sla",
        "pipeline",
    )
    return any(word in q for word in rag_keywords) and not any(word in q for word in app_keywords)


def _rag_is_configured() -> bool:
    if settings.search_provider == "elasticsearch" and settings.llm_provider == "ollama":
        return True
    return all(
        os.getenv(name)
        for name in (
            "AZURE_SEARCH_ENDPOINT",
            "AZURE_SEARCH_INDEX",
            "AZURE_SEARCH_API_KEY",
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
        )
    )


## RAG orchestration: combine retrieval, generation, output guardrails, evaluator, and logs.
def _run_rag_answer(question: str, top_k: int) -> dict:
    # Main RAG orchestration:
    # retrieval -> grounded LLM answer -> output guardrail -> optional evaluator -> logs.
    chunks, search_latency_ms = _search_rag_chunks(question, top_k)
    if not chunks:
        logger.info(
            "rag.request.completed",
            extra={
                "operation": "loanprocessai.rag.ask",
                "top_k": top_k,
                "retrieval_count": 0,
                "search_latency_ms": search_latency_ms,
                "question_length": len(question),
                "app_release": settings.app_release,
                "rag_prompt_version": settings.rag_prompt_version,
                "rag_index_version": settings.rag_index_version,
                "status_code": 200,
            },
        )
        return {
            "question": question,
            "answer": "The indexed documents did not return relevant evidence for this question.",
            "sources": [],
            "retrieval_count": 0,
            "latency_ms": {"search": search_latency_ms, "model": 0},
        }

    answer, model_latency_ms, prompt_length, llm_metadata = _call_rag_chat_model(question, chunks)
    answer, output_guardrail = _apply_output_guardrail(answer, "rag.ask")
    sources = [
        {
            "title": chunk.get("title"),
            "chunk_id": chunk.get("chunk_id"),
            "parent_id": chunk.get("parent_id"),
            "score": chunk.get("@search.score") if chunk.get("@search.score") is not None else chunk.get("score"),
            "reranker_score": chunk.get("rerank_score") if chunk.get("rerank_score") is not None else chunk.get("@search.rerankerScore"),
            "content_preview": _preview_text(chunk.get("chunk", ""), 350),
        }
        for chunk in chunks
    ]

    evaluation = None
    if _is_llm_evaluation_enabled() and not output_guardrail:
        evaluation = evaluate_rag_answer(question, chunks, answer)

    # Emit one PII-safe structured completion log for observability.
    # This lets us query retrieval count, search latency, model latency,
    # prompt/response size, model deployment, and source titles in terminal
    # logs today and Azure Log Analytics after cloud deployment.
    logger.info(
        "rag.request.completed",
        extra={
            "operation": "loanprocessai.rag.ask",
            "top_k": top_k,
            "retrieval_count": len(chunks),
            "search_latency_ms": search_latency_ms,
            "model_latency_ms": model_latency_ms,
            "question_length": len(question),
            "prompt_length": prompt_length,
            "response_length": len(answer),
            "model_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            "source_titles": sorted({str(source.get("title")) for source in sources if source.get("title")}),
            "app_release": settings.app_release,
            "rag_prompt_version": settings.rag_prompt_version,
            "rag_index_version": settings.rag_index_version,
            "llm_trace_mode": settings.llm_trace_mode,
            "evaluation_groundedness": evaluation.get("groundedness") if evaluation else None,
            "evaluation_correctness": evaluation.get("correctness") if evaluation else None,
            "evaluation_answer_relevance": evaluation.get("answer_relevance") if evaluation else None,
            "evaluation_hallucination_risk": evaluation.get("hallucination_risk") if evaluation else None,
            "evaluation_bias_fairness_risk": evaluation.get("bias_fairness_risk") if evaluation else None,
            "evaluation_pii_risk": evaluation.get("pii_risk") if evaluation else None,
            "evaluation_safety": evaluation.get("safety") if evaluation else None,
            "evaluation_policy_compliance": evaluation.get("policy_compliance") if evaluation else None,
            **llm_metadata,
            "status_code": 200,
        },
    )

    if PROMETHEUS_AVAILABLE:
        RAG_SEARCH_LATENCY.observe(search_latency_ms)
        RAG_MODEL_LATENCY.observe(model_latency_ms)
        in_tok = int(llm_metadata.get("input_tokens") or max(250, prompt_length // 4))
        out_tok = int(llm_metadata.get("output_tokens") or max(50, len(answer) // 4))
        LLM_INPUT_TOKENS.inc(in_tok)
        LLM_OUTPUT_TOKENS.inc(out_tok)
        LLM_TOTAL_TOKENS.inc(in_tok + out_tok)
        LLM_REQUESTS_TOTAL.labels(model=settings.litellm_model or settings.ollama_model, status="success").inc()

    result = {
        "question": question,
        "answer": answer,
        "sources": sources,
        "retrieval_count": len(chunks),
        "latency_ms": {
            "search": search_latency_ms,
            "model": model_latency_ms,
        },
    }
    if output_guardrail:
        result["guardrail"] = output_guardrail
    if evaluation:
        result["evaluation"] = evaluation
    return result


# ---------------------------------------------------------------------------
# Customer-portal endpoints 
# ---------------------------------------------------------------------------
@app.post("/applications")
async def create_application_endpoint(request: Request):
    """Create a new application from the customer-portal form."""
    form_data = await request.json()
    return bq_create_application(form_data)


@app.get("/applications")
async def list_applications_endpoint():
    return bq_list_applications()


@app.get("/applications/{application_id}")
async def get_application_endpoint(application_id: str):
    app_row = bq_get_application(application_id)
    if not app_row:
        raise HTTPException(status_code=404, detail="application not found")
    docs = bq_list_documents(application_id)
    return {"application": app_row, "documents": docs}


# ---------------------------------------------------------------------------
# Admin: 
# ---------------------------------------------------------------------------
@app.post("/admin/flush-streaming-buffer")
async def flush_streaming_buffer():
    """Force-flush BigQuery streaming buffers for cases & applications tables.

    Old rows inserted via streaming API sit in a buffer for up to 90 min
    and block UPDATE/DELETE. This copies each table in-place to move
    buffered rows into regular storage.
    """
    results = bq_flush_all_streaming_buffers()
    return {"status": "ok", "results": results}


class SimulationConfigBody(BaseModel):
    delay_ms: int = 0
    delay_step: str = ""
    context_corruption: str = ""


@app.post("/admin/simulation/configure")
async def configure_simulation(body: SimulationConfigBody):
    """Dynamically configure incident simulation variables for testing scenarios."""
    os.environ["SIMULATE_AGENT_STEP_DELAY_MS"] = str(max(0, body.delay_ms))
    os.environ["SIMULATE_AGENT_DELAY_STEP"] = body.delay_step
    os.environ["SIMULATE_AGENT_CONTEXT_CORRUPTION"] = body.context_corruption
    return {
        "status": "ok",
        "simulation": {
            "SIMULATE_AGENT_STEP_DELAY_MS": os.getenv("SIMULATE_AGENT_STEP_DELAY_MS"),
            "SIMULATE_AGENT_DELAY_STEP": os.getenv("SIMULATE_AGENT_DELAY_STEP"),
            "SIMULATE_AGENT_CONTEXT_CORRUPTION": os.getenv("SIMULATE_AGENT_CONTEXT_CORRUPTION"),
        },
    }


@app.post("/admin/simulation/reset")
async def reset_simulation():
    """Reset all incident simulation variables to clean operational baseline."""
    os.environ["SIMULATE_AGENT_STEP_DELAY_MS"] = "0"
    os.environ["SIMULATE_AGENT_DELAY_STEP"] = ""
    os.environ["SIMULATE_AGENT_CONTEXT_CORRUPTION"] = ""
    return {
        "status": "ok",
        "message": "All incident simulations reset to clean baseline.",
    }


@app.get("/admin/simulation/status")
@app.get("/admin/simulation")
async def get_simulation_status():
    """Retrieve current incident simulation fault injection state."""
    try:
        delay_ms = max(0, int(os.getenv("SIMULATE_AGENT_STEP_DELAY_MS", "0")))
    except ValueError:
        delay_ms = 0
    delay_step = os.getenv("SIMULATE_AGENT_DELAY_STEP", "").strip()
    context_corruption = os.getenv("SIMULATE_AGENT_CONTEXT_CORRUPTION", "").strip()
    is_active = bool(delay_ms > 0 or delay_step or context_corruption)
    return {
        "status": "ok",
        "active": is_active,
        "simulation": {
            "SIMULATE_AGENT_STEP_DELAY_MS": delay_ms,
            "SIMULATE_AGENT_DELAY_STEP": delay_step,
            "SIMULATE_AGENT_CONTEXT_CORRUPTION": context_corruption,
        },
    }




@app.delete("/applications/{application_id}")
async def delete_application_endpoint(application_id: str):
    """Delete an application and all related BQ data + GCS files."""
    app_row = bq_get_application(application_id)
    if not app_row:
        raise HTTPException(status_code=404, detail="application not found")
    try:
        result = bq_delete_application(application_id)
        return {"status": "deleted", **result}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/applications/{application_id}/documents")
async def list_documents_endpoint(application_id: str):
    return bq_list_documents(application_id)


@app.get("/applications/{application_id}/documents/{document_id}/url")
async def get_document_url_endpoint(application_id: str, document_id: str):
    """Return a signed URL to view/download the document from GCS."""
    try:
        return bq_get_document_signed_url(application_id, document_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/local-documents/{document_id}")
async def get_local_document_endpoint(document_id: str):
    """Serve a development-mode document; Blob SAS replaces this in Stage 2."""
    from tools import get_local_document_path

    path = get_local_document_path(document_id)
    if path is None:
        raise HTTPException(status_code=404, detail="document not found")
    return FileResponse(str(path))


@app.post("/applications/{application_id}/documents/{document_id}/summary")
async def summarize_document_endpoint(application_id: str, document_id: str):
    """Return a Gemini-generated markdown summary for a single document."""
    try:
        return bq_summarize_document(application_id, document_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/applications/{application_id}/documents")
async def upload_documents_endpoint(
    application_id: str,
    files: list[UploadFile] = File(...),
    doc_types: list[str] | None = Form(default=None),
    uploaded_by: str | None = Form(default=None),
):
    """Upload one or more documents for an application to GCS + BQ."""
    uploaded = []
    errors: list[str] = []
    types_list = doc_types or []
    for idx, f in enumerate(files):
        try:
            data = await f.read()
            doc_type = types_list[idx] if idx < len(types_list) else None
            rec = bq_upload_document(
                application_id=application_id,
                file_bytes=data,
                filename=f.filename or "unknown",
                content_type=f.content_type or "application/octet-stream",
                doc_type=doc_type,
                uploaded_by=uploaded_by,
            )
            uploaded.append(rec)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{f.filename}: {e}")
    return {"uploaded": uploaded, "errors": errors}


@app.get("/customers/{email}/applications")
async def list_customer_applications_endpoint(email: str):
    return bq_list_customer_applications(email)


@app.get("/cases")
async def list_cases_endpoint():
    """List all active cases from the system."""
    return {"cases": bq_list_cases()}


@app.post("/cases")
async def create_case_endpoint(body: CreateCaseBody):
    case = bq_create_case(body.application_id, body.assigned_rm)
    return case



@app.get("/cases/{case_id}")
async def get_case_endpoint(case_id: str):
    """Fetch case details from BigQuery."""
    case = bq_get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case not found")
    return {"case": case}


@app.post("/cases/{case_id}/reset")
async def reset_case_endpoint(case_id: str):
    """Purge stale agent runs and reset case status for clean re-execution."""
    try:
        from tools import reset_case_runs
        res = reset_case_runs(case_id)
        return {"ok": True, "case_id": case_id, "detail": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat/{case_id}")
@observe_operation("loanprocessai.agent.orchestrator_chat")
async def chat(case_id: str, body: ChatBody):
    started = time.perf_counter()
    guardrail = _input_guardrail(body.message)
    if guardrail:
        response = _guardrail_response(body.message, guardrail, "agent.orchestrator_chat")
        return {
            "case_id": case_id,
            "response": response["response"],
            "route": "guardrail",
            "guardrail": response["guardrail"],
            "agent_outputs": {},
        }

    session_id = f"{case_id}:{body.user_id}"
    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=body.user_id, session_id=session_id
    )
    if session is None:
        session = await _session_service.create_session(
            app_name=APP_NAME,
            user_id=body.user_id,
            session_id=session_id,
            state=build_initial_state(case_id, body.user_id),
        )

    content = types.Content(role="user", parts=[types.Part(text=body.message)])
    chunks: list[str] = []
    async for event in _runner.run_async(
        user_id=body.user_id, session_id=session_id, new_message=content
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for p in event.content.parts:
                text_val = getattr(p, "text", None)
                if text_val:
                    chunks.append(str(text_val))

    # Pull each sub-agent's output_key from session state so the frontend can
    # render them in their own panels (no Python logic / parsing).
    final_session = await _session_service.get_session(
        app_name=APP_NAME, user_id=body.user_id, session_id=session_id
    )
    state = final_session.state if final_session else {}
    agent_outputs = {
        "document_intake": state.get("document_intake_output"),
        "kyc": state.get("kyc_output"),
        "financial": state.get("financial_output"),
        "memo": state.get("memo_output"),
        "decision": state.get("decision_output"),
        "closing": state.get("closing_output"),
        "chatbot": state.get("chatbot_output"),
    }
    response_text = "\n".join(chunks)
    response_text, output_guardrail = _apply_output_guardrail(response_text, "agent.orchestrator_chat")
    response = {
        "case_id": case_id,
        "response": response_text,
        "agent_outputs": agent_outputs,
    }
    if output_guardrail:
        response["route"] = "guardrail"
        response["guardrail"] = output_guardrail
    logger.info(
        "agent.request.completed",
        extra={
            "operation": "loanprocessai.agent.orchestrator_chat",
            "agent_name": "orchestrator",
            "case_id": case_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "output_length": len(response_text),
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )
    return response


@app.post("/chat/{case_id}/agent/{agent_name}")
@observe_operation("loanprocessai.agent.single_run")
async def chat_single_agent(case_id: str, agent_name: str, body: ChatBody):
    """Run ONE sub-agent directly (used by per-tab re-run buttons).

    Bypasses the root orchestrator so that single-agent re-runs always
    work, regardless of pipeline structure.
    """
    started = time.perf_counter()
    guardrail = _input_guardrail(body.message)
    if guardrail:
        response = _guardrail_response(body.message, guardrail, "agent.single_run")
        return {
            "case_id": case_id,
            "agent": agent_name,
            "response": response["response"],
            "output": response["response"],
            "route": "guardrail",
            "guardrail": response["guardrail"],
        }

    runner = _individual_runners.get(agent_name)
    if runner is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown agent '{agent_name}'. Known: {list(_individual_runners)}",
        )
    session_id = f"{case_id}:{body.user_id}:{agent_name}"
    # Always build fresh state from BQ so the agent sees the latest upstream
    # outputs. Delete any stale session first (InMemorySessionService throws
    # if you create with a duplicate session_id).
    try:
        await _session_service.delete_session(
            app_name=APP_NAME, user_id=body.user_id, session_id=session_id
        )
    except Exception:  # noqa: BLE001
        pass  # session didn't exist — fine
    init_state = build_initial_state(case_id, body.user_id)
    for _, out_key in _PIPELINE_STEPS.get("pre_approval", []):
        init_state[out_key] = ""
    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=body.user_id,
        session_id=session_id,
        state=init_state,
    )

    content = types.Content(role="user", parts=[types.Part(text=body.message)])
    chunks: list[str] = []
    all_text: list[str] = []  # fallback: capture ALL non-thought text events
    try:
        async for event in runner.run_async(
            user_id=body.user_id, session_id=session_id, new_message=content
        ):
            if event.content and event.content.parts:
                for p in event.content.parts:
                    text_val = getattr(p, "text", None)
                    if text_val and not getattr(p, "thought", False):
                        all_text.append(str(text_val))
            if event.is_final_response() and event.content and event.content.parts:
                for p in event.content.parts:
                    text_val = getattr(p, "text", None)
                    if text_val and not getattr(p, "thought", False):
                        chunks.append(str(text_val))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

    final_session = await _session_service.get_session(
        app_name=APP_NAME, user_id=body.user_id, session_id=session_id
    )
    state = final_session.state if final_session else {}
    output_key = _AGENT_OUTPUT_KEY.get(agent_name)
    output_text = state.get(output_key) if output_key else None
    # Fallback: if output_key wasn't written, use captured text from events.
    response_text = "\n".join(chunks) or "\n".join(all_text)
    response_text, output_guardrail = _apply_output_guardrail(response_text, "agent.single_run")
    if not output_text and response_text:
        output_text = response_text
    response = {
        "case_id": case_id,
        "agent": agent_name,
        "response": response_text,
        "output": output_text,
    }
    if output_guardrail:
        response["route"] = "guardrail"
        response["guardrail"] = output_guardrail
        response["output"] = response_text
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    prompt_tokens = max(100, len(body.message) // 4 + 800)
    completion_tokens = max(50, len(response_text) // 4)
    total_tokens = prompt_tokens + completion_tokens

    if PROMETHEUS_AVAILABLE:
        AGENT_EXECUTIONS.labels(agent_name=agent_name).inc()
        dur_s = max(0.001, duration_ms / 1000.0)
        AGENT_EXECUTION_DURATION_SECONDS.labels(agent_name=agent_name).observe(dur_s)
        AGENT_STAGE_LATENCY_SECONDS.labels(agent_name=agent_name).set(dur_s)
        if agent_name not in _AGENT_STAGE_STATS:
            _AGENT_STAGE_STATS[agent_name] = {"success": 0, "total": 0}
        _AGENT_STAGE_STATS[agent_name]["total"] += 1
        _AGENT_STAGE_STATS[agent_name]["success"] += 1
        rate = (_AGENT_STAGE_STATS[agent_name]["success"] / _AGENT_STAGE_STATS[agent_name]["total"]) * 100.0
        AGENT_STAGE_SUCCESS_RATE.labels(agent_name=agent_name).set(round(rate, 1))
        RAG_MODEL_LATENCY.observe(duration_ms)
        LLM_INPUT_TOKENS.inc(prompt_tokens)
        LLM_OUTPUT_TOKENS.inc(completion_tokens)
        LLM_TOTAL_TOKENS.inc(total_tokens)

    logger.info(
        "agent.request.completed",
        extra={
            "operation": "loanprocessai.agent.single_run",
            "agent_name": agent_name,
            "case_id": case_id,
            "duration_ms": duration_ms,
            "output_length": len(response_text),
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )

    logger.info(
        "llm.request.completed",
        extra={
            "operation": "loanprocessai.agent.single_run",
            "llm_route": f"agent_{agent_name}",
            "llm_phase": "generation",
            "llm_status": "success",
            "agent_name": agent_name,
            "case_id": case_id,
            "model_latency_ms": duration_ms,
            "duration_ms": duration_ms,
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "finish_reason": "stop",
            "llm_response_model": settings.ollama_model,
            "model_deployment": settings.litellm_model,
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )
    return response


# ---------------------------------------------------------------------------
# Deterministic pipeline endpoints (no LLM routing)
# ---------------------------------------------------------------------------
## Agent observability: pre-approval emits process-level and step-level telemetry.
@app.post("/process/{case_id}")
@observe_operation("loanprocessai.pipeline.pre_approval")
async def process_case(case_id: str, body: ProcessBody):
    """API #1: Run Pre-Approval Pipeline at submission time.
    
    Deterministically runs all 5 agents in order:
    Document_Intake -> KYC -> Financial -> Memo -> Decision
    
    Call this ONCE when the application is submitted.
    """
    started = time.perf_counter()
    session_id = f"{case_id}:{body.user_id}:pre_approval"
    
    # Always create a fresh session for deterministic runs
    try:
        await _session_service.delete_session(
            app_name=APP_NAME, user_id=body.user_id, session_id=session_id
        )
    except Exception:
        pass
    
    init_state = build_initial_state(case_id, body.user_id)
    for _, out_key in _PIPELINE_STEPS.get("pre_approval", []):
        init_state[out_key] = ""
    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=body.user_id,
        session_id=session_id,
        state=init_state,
    )
    
    # Trigger the pre-approval pipeline with a simple start message
    content = types.Content(
        role="user",
        parts=[types.Part(text="Process this loan application.")]
    )
    
    chunks: list[str] = []
    completed_steps: set[str] = set()
    step_started_at = time.perf_counter()
    try:
        async for event in _pre_approval_runner.run_async(
            user_id=body.user_id, session_id=session_id, new_message=content
        ):
            step_started_at = await _log_new_pipeline_steps(
                pipeline="pre_approval",
                case_id=case_id,
                user_id=body.user_id,
                session_id=session_id,
                completed_steps=completed_steps,
                step_started_at=step_started_at,
            )
            if event.is_final_response() and event.content and event.content.parts:
                for p in event.content.parts:
                    text_val = getattr(p, "text", None)
                    if text_val and not getattr(p, "thought", False):
                        chunks.append(str(text_val))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))
    
    # Get all agent outputs from session state
    final_session = await _session_service.get_session(
        app_name=APP_NAME, user_id=body.user_id, session_id=session_id
    )
    state = final_session.state if final_session else {}
    for step_order, (agent_name, output_key) in enumerate(_PIPELINE_STEPS["pre_approval"], start=1):
        if agent_name not in completed_steps:
            _log_agent_step(
                pipeline="pre_approval",
                agent_name=agent_name,
                case_id=case_id,
                step_order=step_order,
                duration_ms=(time.perf_counter() - step_started_at) * 1000,
                output_text=state.get(output_key),
                status="missing_output",
            )
    
    response_text = "\n".join(chunks)
    logger.info(
        "agent.request.completed",
        extra={
            "operation": "loanprocessai.pipeline.pre_approval",
            "agent_name": "pre_approval_pipeline",
            "pipeline": "pre_approval",
            "case_id": case_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "output_length": len(response_text),
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )
    persisted_outputs = bq_get_persisted_agent_outputs(case_id) or {}
    return {
        "case_id": case_id,
        "pipeline": "pre_approval",
        "response": response_text,
        "agent_outputs": {
            "document_intake": state.get("document_intake_output") or persisted_outputs.get("document_intake"),
            "kyc": state.get("kyc_output") or persisted_outputs.get("kyc"),
            "financial": state.get("financial_output") or persisted_outputs.get("financial"),
            "memo": state.get("memo_output") or persisted_outputs.get("memo"),
            "decision": state.get("decision_output") or persisted_outputs.get("decision"),
        },
    }


@app.post("/pipeline/pre_approval")
@observe_operation("loanprocessai.pipeline.pre_approval")
async def pipeline_pre_approval(body: PipelinePreApprovalBody):
    """Convenience endpoint matching the Capstone SME Handson guides.
    
    Accepts either an application submission or case ID, initializes state,
    and runs the 5-agent sequential pre-approval pipeline.
    """
    cid = body.case_id or (f"CASE-{body.application_id}" if body.application_id else f"CASE-{uuid.uuid4().hex[:6].upper()}")
    
    if body.force_financial_corruption:
        os.environ["SIMULATE_AGENT_CONTEXT_CORRUPTION"] = "memo"
    
    result = await process_case(case_id=cid, body=ProcessBody(user_id=body.user_id))
    agent_outputs = result.get("agent_outputs", {})
    return {
        "status": "success",
        "case_id": cid,
        "application_id": body.application_id or cid,
        "pipeline": "pre_approval",
        "response": result.get("response", ""),
        "kyc_output": agent_outputs.get("kyc"),
        "financial_output": agent_outputs.get("financial"),
        "memo_output": agent_outputs.get("memo"),
        "decision_output": agent_outputs.get("decision"),
        "agent_outputs": agent_outputs,
    }


@app.post("/decide/{case_id}")
@observe_operation("loanprocessai.pipeline.post_approval")
async def decide_case(case_id: str, body: DecideBody):
    """API #2: Run Post-Approval Pipeline at decision time.
    
    Deterministically runs the Closing agent after human approval/rejection.
    
    Call this ONCE when the human approves or rejects the application.
    Pass decision as "APPROVED" or "REJECTED".
    """
    started = time.perf_counter()
    decision = body.decision.upper()
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'APPROVED' or 'REJECTED'"
        )
    
    # Record the decision in BigQuery (case status + audit log)
    # This now returns a detailed status message
    decision_record_status = bq_record_human_decision(case_id, decision, body.user_id)
    if PROMETHEUS_AVAILABLE:
        LOAN_DECISIONS_TOTAL.labels(verdict=decision).inc()
    
    session_id = f"{case_id}:{body.user_id}:post_approval"
    
    # Always create a fresh session for deterministic runs
    try:
        await _session_service.delete_session(
            app_name=APP_NAME, user_id=body.user_id, session_id=session_id
        )
    except Exception:
        pass
    
    init_state = build_initial_state(case_id, body.user_id)
    for _, out_key in _PIPELINE_STEPS.get("pre_approval", []):
        init_state[out_key] = ""
    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=body.user_id,
        session_id=session_id,
        state=init_state,
    )
    
    # Pass the decision to the closing agent
    content = types.Content(
        role="user",
        parts=[types.Part(text=f"Manager decision: {decision} by {body.user_id}. Run the Closing Package Agent.")]
    )
    
    chunks: list[str] = []
    completed_steps: set[str] = set()
    step_started_at = time.perf_counter()
    try:
        async for event in _post_approval_runner.run_async(
            user_id=body.user_id, session_id=session_id, new_message=content
        ):
            step_started_at = await _log_new_pipeline_steps(
                pipeline="post_approval",
                case_id=case_id,
                user_id=body.user_id,
                session_id=session_id,
                completed_steps=completed_steps,
                step_started_at=step_started_at,
            )
            if event.is_final_response() and event.content and event.content.parts:
                for p in event.content.parts:
                    text_val = getattr(p, "text", None)
                    if text_val and not getattr(p, "thought", False):
                        chunks.append(str(text_val))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))
    
    # Get closing output from session state
    final_session = await _session_service.get_session(
        app_name=APP_NAME, user_id=body.user_id, session_id=session_id
    )
    state = final_session.state if final_session else {}
    for step_order, (agent_name, output_key) in enumerate(_PIPELINE_STEPS["post_approval"], start=1):
        if agent_name not in completed_steps:
            _log_agent_step(
                pipeline="post_approval",
                agent_name=agent_name,
                case_id=case_id,
                step_order=step_order,
                duration_ms=(time.perf_counter() - step_started_at) * 1000,
                output_text=state.get(output_key),
                status="missing_output",
            )
    
    response_text = "\n".join(chunks)
    logger.info(
        "agent.request.completed",
        extra={
            "operation": "loanprocessai.pipeline.post_approval",
            "agent_name": "post_approval_pipeline",
            "pipeline": "post_approval",
            "case_id": case_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "output_length": len(response_text),
            "status_code": 200,
            "app_release": settings.app_release,
        },
    )
    persisted_outputs = bq_get_persisted_agent_outputs(case_id) or {}
    return {
        "case_id": case_id,
        "pipeline": "post_approval",
        "decision": decision,
        "decision_record_status": decision_record_status,
        "response": response_text,
        "agent_outputs": {
            "closing": state.get("closing_output") or persisted_outputs.get("closing"),
        },
    }


## LoanAssist observability: guardrails, optional RAG routing, and agent request telemetry.
@app.post("/ask")
@observe_operation("loanprocessai.agent.loan_assist")
async def ask_chatbot(body: AskBody):
    """API #3: Standalone chatbot for queries about cases/applications.
    
    Input context from BigQuery:
    - Case management list (all cases)
    - Application list (all applications)  
    - Agent outputs (if case_id is provided)
    
    This does NOT trigger any pipeline - it's read-only Q&A.
    """
    started = time.perf_counter()
    guardrail = _input_guardrail(body.question)
    if guardrail:
        response = _guardrail_response(body.question, guardrail, "agent.loan_assist")
        response["case_id"] = body.case_id
        return response

    if _should_use_rag(body.question) and _rag_is_configured():
        top_k = settings.rag_top_k
        rag_result = _run_rag_answer(body.question.strip(), max(1, min(top_k, 10)))
        source_names = [
            source.get("title") or source.get("parent_id")
            for source in rag_result.get("sources", [])
            if source.get("title") or source.get("parent_id")
        ]
        source_text = ""
        if source_names:
            source_text = "\n\nSources:\n" + "\n".join(f"- {name}" for name in dict.fromkeys(source_names))
        response_text = f"{rag_result['answer']}{source_text}"
        response_text, output_guardrail = _apply_output_guardrail(response_text, "agent.loan_assist")
        response = {
            "question": body.question,
            "case_id": body.case_id,
            "response": response_text,
            "route": "rag",
            "rag": {
                "retrieval_count": rag_result.get("retrieval_count", 0),
                "latency_ms": rag_result.get("latency_ms", {}),
                "sources": rag_result.get("sources", []),
                "evaluation": rag_result.get("evaluation"),
            },
        }
        if output_guardrail:
            response["guardrail"] = output_guardrail
        logger.info(
            "agent.request.completed",
            extra={
                "operation": "loanprocessai.agent.loan_assist",
                "agent_name": "loan_assist_rag_router",
                "case_id": body.case_id,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "output_length": len(response_text),
                "status_code": 200,
                "app_release": settings.app_release,
                "loanassist_prompt_version": settings.loanassist_prompt_version,
            },
        )
        return response
    
    # Fetch context from BigQuery
    cases_list = bq_list_cases()
    applications_list = bq_list_applications()
    
    # Build concise, high-signal context for the chatbot
    context_parts = []
    agent_outputs = {}
    if body.case_id:
        this_case = next((c for c in cases_list if c.get("case_id") == body.case_id), None)
        if this_case:
            context_parts.append(f"## Current Case: {body.case_id}")
            context_parts.append(f"- Status: {this_case.get('status')}")
            context_parts.append(f"- Assigned RM: {this_case.get('assigned_rm')}")
            context_parts.append(f"- Application ID: {this_case.get('application_id')}")

        agent_outputs = bq_get_persisted_agent_outputs(body.case_id)
        if agent_outputs:
            context_parts.append("\n## Current Case Agent Findings (Summary):")
            for ag_name, ag_text in agent_outputs.items():
                if ag_text:
                    summary_text = str(ag_text)[:600]
                    context_parts.append(f"- **{ag_name.upper()}**: {summary_text}")
    else:
        context_parts.append("## Active Pipeline Cases Overview:")
        for c in cases_list[:10]:
            context_parts.append(f"- Case {c.get('case_id')}: App {c.get('application_id')}, Status: {c.get('status')}, RM: {c.get('assigned_rm')}")
        context_parts.append("\n## Recent Loan Applications:")
        for a in applications_list[:10]:
            context_parts.append(f"- App {a.get('application_id')}: Borrower: {a.get('business_legal_name', 'N/A')}, Amount: ${a.get('loan_amount', 'N/A')}, Status: {a.get('status')}")

    context_text = "\n".join(context_parts)

    # Create session for chatbot
    session_id = f"ask:{body.user_id}:{body.case_id or 'global'}"

    try:
        await _session_service.delete_session(
            app_name=APP_NAME, user_id=body.user_id, session_id=session_id
        )
    except Exception:
        pass

    # Build initial state with compact context
    initial_state = {
        "cases_list": cases_list[:10],
        "applications_list": applications_list[:10],
        "case_id": body.case_id,
        "actor": body.user_id,
        "case": {},
        "application": {},
        "documents": [],
        "document_intake_output": str(agent_outputs.get("document_intake", ""))[:1500],
        "kyc_output": str(agent_outputs.get("kyc", ""))[:1500],
        "financial_output": str(agent_outputs.get("financial", ""))[:1500],
        "memo_output": str(agent_outputs.get("memo", ""))[:1500],
        "decision_output": str(agent_outputs.get("decision", ""))[:1500],
        "closing_output": str(agent_outputs.get("closing", ""))[:1500],
    }

    if body.case_id:
        _populate_state_dict(initial_state)

    await _session_service.create_session(
        app_name=APP_NAME,
        user_id=body.user_id,
        session_id=session_id,
        state=initial_state,
    )

    prompt_text = f"""Here is the current commercial lending pipeline context:

{context_text}

User Question: {body.question}

Please answer concisely based on the data provided above."""
    
    content = types.Content(
        role="user",
        parts=[types.Part(text=prompt_text)]
    )
    
    # Use the chatbot agent runner
    chatbot_runner = _individual_runners.get("chatbot")
    if not chatbot_runner:
        raise HTTPException(status_code=500, detail="Chatbot agent not available")
    
    chunks: list[str] = []
    try:
        async for event in chatbot_runner.run_async(
            user_id=body.user_id, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for p in event.content.parts:
                    text_val = getattr(p, "text", None)
                    if text_val and not getattr(p, "thought", False):
                        chunks.append(str(text_val))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))
    
    response_text = "\n".join(chunks)
    response_text, output_guardrail = _apply_output_guardrail(response_text, "agent.loan_assist")
    response = {
        "question": body.question,
        "case_id": body.case_id,
        "response": response_text,
        "context_summary": {
            "cases_count": len(cases_list),
            "applications_count": len(applications_list),
            "has_agent_outputs": bool(body.case_id and any(agent_outputs.values())),
        },
    }
    if output_guardrail:
        response["route"] = "guardrail"
        response["guardrail"] = output_guardrail
    logger.info(
        "agent.request.completed",
        extra={
            "operation": "loanprocessai.agent.loan_assist",
            "agent_name": "chatbot",
            "case_id": body.case_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "output_length": len(response_text),
            "status_code": 200,
            "app_release": settings.app_release,
            "loanassist_prompt_version": settings.loanassist_prompt_version,
        },
    )
    return response


## Direct RAG endpoint: useful for testing retrieval, generation, guardrails, and telemetry.
@app.post("/rag/ask")
@observe_operation("loanprocessai.rag.ask")
async def ask_rag(body: RagAskBody):
    """Grounded RAG Q&A over Azure AI Search indexed documents."""
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    guardrail = _input_guardrail(question)
    if guardrail:
        response = _guardrail_response(question, guardrail, "rag.ask")
        return {
            "question": question,
            "answer": response["response"],
            "sources": [],
            "retrieval_count": 0,
            "latency_ms": {"search": 0, "model": 0},
            "route": "guardrail",
            "guardrail": response["guardrail"],
        }

    top_k = body.top_k or settings.rag_top_k
    top_k = max(1, min(top_k, 10))

    return _run_rag_answer(question, top_k)


@app.get("/cases/{case_id}/agent_outputs")
async def get_case_agent_outputs(case_id: str):
    """Return the latest persisted output for each agent on this case.

    Read-only — never invokes an agent. Used by the frontend to hydrate the
    per-agent panels when localStorage is empty (incognito, new browser,
    cache cleared) so the user always sees prior runs without re-firing the
    pipeline.
    """
    return {
        "case_id": case_id,
        "agent_outputs": bq_get_persisted_agent_outputs(case_id),
    }


# ---------------------------------------------------------------------------
# Serve React frontend (production / Cloud Run)
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR / "static")), name="frontend-static")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Catch-all: serve React index.html for client-side routing."""
        file_path = _STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_STATIC_DIR / "index.html"))
