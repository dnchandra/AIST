"""Centralized runtime configuration for LoanProcessAI.

Values still come from environment variables or `.env`. This module gives the
application one clear place to read deployment metadata, feature switches, and
safe non-secret configuration for readiness/observability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_release: str = os.getenv("APP_RELEASE", "local-dev")
    rag_prompt_version: str = os.getenv("RAG_PROMPT_VERSION", "rag-prompt-v1")
    loanassist_prompt_version: str = os.getenv(
        "LOANASSIST_PROMPT_VERSION", "loanassist-prompt-v1"
    )
    rag_index_version: str = os.getenv("RAG_INDEX_VERSION", "rag-index-v1")
    llm_trace_mode: str = os.getenv("LLM_TRACE_MODE", "metadata")

    azure_openai_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    azure_openai_api_version: str = os.getenv(
        "AZURE_OPENAI_API_VERSION", "2025-04-01-preview"
    )
    azure_openai_evaluator_deployment: str = os.getenv(
        "AZURE_OPENAI_EVALUATOR_DEPLOYMENT",
        os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
    )

    azure_search_index: str = os.getenv("AZURE_SEARCH_INDEX", "")
    azure_search_api_version: str = os.getenv("AZURE_SEARCH_API_VERSION", "2024-07-01")
    rag_top_k: int = _int_env("RAG_TOP_K", 5)

    guardrails_enabled: bool = _bool_env("GUARDRAILS_ENABLED", True)
    llm_evaluation_enabled: bool = _bool_env("LLM_EVALUATION_ENABLED", False)

    # Local / On-Premise Profiles
    llm_provider: str = os.getenv("LLM_PROVIDER", "azure").strip().lower()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "ornith-1.5:35b")
    ollama_embedding_model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "embeddinggemma-2:740m")

    search_provider: str = os.getenv("SEARCH_PROVIDER", "azure").strip().lower()
    elasticsearch_url: str = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200").rstrip("/")
    elasticsearch_index: str = os.getenv("ELASTICSEARCH_INDEX", "loanprocessai-rag")
    rag_candidate_k: int = _int_env("RAG_CANDIDATE_K", 25)
    reranker_enabled: bool = _bool_env("RERANKER_ENABLED", True)
    reranker_model: str = os.getenv("RERANKER_MODEL", "ms-marco-TinyBERT-L-2-v2")
    prometheus_enabled: bool = _bool_env("PROMETHEUS_ENABLED", True)
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Portal & Platform Credentials
    azure_portal_url: str = os.getenv("AZURE_PORTAL_URL", "https://portal.azure.com/")
    azure_portal_username: str = os.getenv("AZURE_PORTAL_USERNAME", "")
    langsmith_username: str = os.getenv("LANGSMITH_USERNAME", "")

    @property
    def litellm_model(self) -> str:
        if self.llm_provider == "ollama":
            return f"ollama/{self.ollama_model}"
        return self.azure_openai_deployment or f"ollama/{self.ollama_model}"


settings = Settings()
