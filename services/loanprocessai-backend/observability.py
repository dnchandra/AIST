"""Observability primitives shared by the LoanProcessAI API.

Console logs are structured JSON for local development and Azure Container
Apps. Azure Monitor export is deliberately optional: set the Application
Insights connection string only in the target environment.
"""

from __future__ import annotations

import contextvars
import functools
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any, Awaitable, Callable, TypeVar

# Correlation context: keeps the current request ID available to all logs in this async request.
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
_configured = False
logger = logging.getLogger("loanprocessai")
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

# Enterprise Telemetry Path: logs/telemetry/loanprocessai.jsonl (ELK / Splunk ingestion ready)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CENTRAL_LOG = _REPO_ROOT / "logs" / "telemetry" / "loanprocessai.jsonl"
_LEGACY_LOG = Path(__file__).resolve().parent / "logs" / "loanprocessai.jsonl"


def resolve_default_log_path() -> Path:
    """Resolve active local structured log path: central telemetry first, legacy fallback."""
    for container_dir in (Path("/app/logs/telemetry"), Path("/logs/telemetry")):
        if container_dir.parent.is_dir():
            return container_dir / "loanprocessai.jsonl"
    if (_REPO_ROOT / "logs").is_dir():
        return _CENTRAL_LOG
    return _LEGACY_LOG


DEFAULT_LOCAL_LOG_PATH = resolve_default_log_path()


class JsonFormatter(logging.Formatter):
    """Write one JSON object per log line for Container Apps / Log Analytics."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z")
        active_trace = getattr(record, "trace_id", None) or trace_id() or ""
        payload: dict[str, Any] = {
            "timestamp": ts,
            "@timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": current_correlation_id(),
            "trace_id": active_trace,
        }
        # Only fields listed here are copied from logger.extra into the JSON payload.
        # This keeps telemetry useful while avoiding accidental full prompt/body logging.
        for key in (
            # Standard HTTP/API observability fields.
            "operation",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "usage_source",
            # RAG observability fields emitted from app.py:
            # search_latency_ms = Azure AI Search retrieval time.
            # model_latency_ms = Azure OpenAI generation time.
            # prompt/response lengths help explain latency and cost.
            "top_k",
            "retrieval_count",
            "search_latency_ms",
            "model_latency_ms",
            "question_length",
            "prompt_length",
            "response_length",
            "max_completion_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "finish_reason",
            "content_filter_results",
            "prompt_filter_results",
            "llm_response_id",
            "llm_response_model",
            "system_fingerprint",
            "debug_prompt",
            "debug_chunks",
            "debug_answer",
            "model_deployment",
            "source_titles",
            "guardrail_type",
            "guardrail_action",
            "guardrail_reason",
            "evaluation_groundedness",
            "evaluation_correctness",
            "evaluation_answer_relevance",
            "evaluation_hallucination_risk",
            "evaluation_bias_fairness_risk",
            "evaluation_pii_risk",
            "evaluation_safety",
            "evaluation_policy_compliance",
            "llm_route",
            "llm_phase",
            "llm_status",
            "llm_error_type",
            "agent_name",
            "case_id",
            "pipeline",
            "step_order",
            "step_status",
            "output_length",
            "app_release",
            "rag_prompt_version",
            "loanassist_prompt_version",
            "rag_index_version",
            "llm_trace_mode",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def current_correlation_id() -> str:
    """Return the correlation ID currently attached to this request."""
    return _correlation_id.get()


def new_correlation_id(candidate: str | None = None) -> str:
    """Accept a bounded caller ID or generate an opaque request identifier."""
    if candidate and len(candidate) <= 128 and candidate.replace("-", "").replace("_", "").isalnum():
        return candidate
    return str(uuid.uuid4())


def set_correlation_id(correlation_id: str) -> contextvars.Token[str]:
    """Attach a correlation ID to the current request context."""
    return _correlation_id.set(correlation_id)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    """Restore the previous correlation context after the request finishes."""
    _correlation_id.reset(token)


def trace_id() -> str | None:
    """Return the active W3C trace ID when OpenTelemetry is installed."""
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        return format(context.trace_id, "032x") if context.is_valid else None
    except ImportError:
        return None


def _metadata_value(value: Any) -> Any:
    """Convert SDK response objects to JSON-safe metadata without prompt text."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_metadata_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _metadata_value(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        return _metadata_value(value.model_dump())
    if hasattr(value, "dict"):
        return _metadata_value(value.dict())
    return str(value)


def extract_llm_response_metadata(response: Any) -> dict[str, Any]:
    """Extract safe token/filter metadata from a Chat Completions response."""
    metadata: dict[str, Any] = {}

    usage = getattr(response, "usage", None)
    if usage is not None:
        metadata["input_tokens"] = getattr(usage, "prompt_tokens", None)
        metadata["output_tokens"] = getattr(usage, "completion_tokens", None)
        metadata["total_tokens"] = getattr(usage, "total_tokens", None)

    choices = getattr(response, "choices", None) or []
    if choices:
        choice = choices[0]
        metadata["finish_reason"] = getattr(choice, "finish_reason", None)
        metadata["content_filter_results"] = _metadata_value(
            getattr(choice, "content_filter_results", None)
        )

    metadata["prompt_filter_results"] = _metadata_value(
        getattr(response, "prompt_filter_results", None)
    )
    metadata["llm_response_id"] = getattr(response, "id", None)
    metadata["llm_response_model"] = getattr(response, "model", None)
    metadata["system_fingerprint"] = getattr(response, "system_fingerprint", None)

    return {key: value for key, value in metadata.items() if value is not None}


def configure_observability() -> None:
    """Configure JSON logs and optional Azure Monitor OpenTelemetry export."""
    global _configured
    if _configured:
        return
    _configured = True

    # Local and cloud logs both go to stdout as structured JSON.
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)

    # Local AIOps practice: write structured events to centralized JSONL file (ELK/Splunk ready).
    # Disable with LOCAL_FILE_LOG_ENABLED=false or override path with LOCAL_LOG_FILE.
    log_path: Path | None = None
    if os.getenv("LOCAL_FILE_LOG_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        raw_log = os.getenv("LOCAL_LOG_FILE")
        if raw_log:
            candidate = Path(raw_log)
            if candidate.is_absolute():
                log_path = candidate
            elif Path("/app/logs").is_dir():
                log_path = Path("/app") / candidate
            elif Path("/logs").is_dir():
                log_path = Path("/") / candidate
            else:
                log_path = _REPO_ROOT / candidate
        else:
            log_path = resolve_default_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        logger.addHandler(file_handler)

        # Dual-sync to legacy path if distinct and legacy folder exists,
        # guaranteeing zero regression for any tools referencing backend/logs/
        if log_path.resolve() != _LEGACY_LOG.resolve() and _LEGACY_LOG.parent.exists():
            try:
                _LEGACY_LOG.parent.mkdir(parents=True, exist_ok=True)
                legacy_handler = logging.FileHandler(_LEGACY_LOG, encoding="utf-8")
                legacy_handler.setFormatter(JsonFormatter())
                logger.addHandler(legacy_handler)
            except OSError:
                pass

    # If Application Insights is configured and installed, Azure Monitor receives telemetry.
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    azure_configured = False
    if connection_string:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor

            configure_azure_monitor(
                connection_string=connection_string,
                logger_name="loanprocessai",
                enable_trace_based_sampling_for_logs=True,
            )
            logger.info("observability.configured", extra={"operation": "azure_monitor"})
            azure_configured = True
        except ImportError:
            azure_configured = False

    # Always configure local OpenTelemetry OTLP export if OTEL_EXPORTER_OTLP_ENDPOINT is available
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318")
    if otlp_endpoint:
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.resources import Resource
            import importlib

            provider = trace.get_tracer_provider()
            if not isinstance(provider, TracerProvider):
                resource = Resource.create({
                    "service.name": "loanprocessai-backend",
                    "deployment.environment": os.getenv("ENVIRONMENT", "local"),
                    "service.version": os.getenv("APP_RELEASE", "v1.0.0"),
                })
                provider = TracerProvider(resource=resource)
                trace.set_tracer_provider(provider)

            mod = importlib.import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
            otlp_cls = getattr(mod, "OTLPSpanExporter")
            span_exporter = otlp_cls(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(span_exporter))
            logger.info(
                "observability.configured",
                extra={
                    "operation": "local_otlp",
                    "endpoint": otlp_endpoint,
                    "path": str(log_path) if log_path else "",
                },
            )
        except Exception as e:
            logger.debug("local_otlp.not_configured", extra={"error": str(e)})


def observe_operation(operation: str) -> Callable[[F], F]:
    """Create a business span and duration metric around an async endpoint."""
    def decorate(function: F) -> F:
        @functools.wraps(function)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            try:
                from opentelemetry import metrics, trace

                tracer = trace.get_tracer("loanprocessai.operations")
                meter = metrics.get_meter("loanprocessai.operations")
                duration = meter.create_histogram("loanprocessai.operation.duration", unit="ms")
                calls = meter.create_counter("loanprocessai.operation.calls")
                # Business-level span: useful for viewing pipeline/agent/RAG operations.
                with tracer.start_as_current_span(operation) as span:
                    span.set_attribute("loanprocessai.operation", operation)
                    result = await function(*args, **kwargs)
                    elapsed = round((time.perf_counter() - started) * 1000, 2)
                    duration.record(elapsed, {"operation": operation, "outcome": "success"})
                    calls.add(1, {"operation": operation, "outcome": "success"})
                    return result
            except ImportError:
                # App still runs if OpenTelemetry packages are unavailable.
                return await function(*args, **kwargs)
            except Exception:
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                logger.exception(
                    "operation.failed",
                    extra={"operation": operation, "duration_ms": elapsed, "trace_id": trace_id()},
                )
                raise

        return wrapped  # type: ignore[return-value]

    return decorate
