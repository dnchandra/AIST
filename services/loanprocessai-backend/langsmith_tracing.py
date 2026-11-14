"""backend/langsmith_tracing.py

Guarded LiteLLM LangSmith callback registration.
Off by default; activated when LANGSMITH_TRACING is enabled and LANGSMITH_API_KEY is present.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("loanprocessai")


def configure_langsmith_tracing() -> None:
    """Register LiteLLM callbacks for LangSmith tracing if configured."""
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").strip().lower() in {"1", "true", "yes"}
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()

    if tracing_enabled and api_key:
        endpoint = (
            os.getenv("LANGSMITH_ENDPOINT")
            or os.getenv("LANGSMITH_BASE_URL")
            or "https://api.smith.langchain.com"
        ).rstrip("/")
        project = os.getenv("LANGSMITH_PROJECT", "ailoanappbydnc").strip('"\'')
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
        os.environ["LANGSMITH_BASE_URL"] = endpoint
        os.environ["LANGSMITH_PROJECT"] = project
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_TRACING"] = "true"

        try:
            import litellm
            from litellm.integrations.langsmith import LangsmithLogger

            # Ensure LangsmithLogger instance is attached directly to litellm.callbacks
            has_ls = any(isinstance(cb, LangsmithLogger) for cb in (litellm.callbacks or []))
            if not has_ls:
                ls_logger = LangsmithLogger(
                    langsmith_api_key=api_key,
                    langsmith_project=project,
                    langsmith_base_url=endpoint,
                )
                if litellm.callbacks is None:
                    litellm.callbacks = []
                litellm.callbacks.append(ls_logger)

            curr_success = set(litellm.success_callback or [])
            curr_failure = set(litellm.failure_callback or [])
            curr_success.add("langsmith")
            curr_failure.add("langsmith")
            litellm.success_callback = list(curr_success)
            litellm.failure_callback = list(curr_failure)

            logger.info(
                "langsmith.tracing.enabled",
                extra={
                    "operation": "langsmith_tracing",
                    "project": project,
                    "endpoint": endpoint,
                },
            )
        except Exception as exc:
            logger.warning(
                "langsmith.tracing.configuration_failed",
                extra={"operation": "langsmith_tracing", "error": str(exc)},
            )
    else:
        logger.info(
            "langsmith.tracing.disabled",
            extra={"operation": "langsmith_tracing"},
        )
