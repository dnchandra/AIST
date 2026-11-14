"""Shared, provider-neutral model configuration for all sub-agents."""

import os
from pathlib import Path

import dotenv
import litellm
from google.adk.models.lite_llm import LiteLlm

# Retry on momentary rate limits with exponential backoff
litellm.num_retries = 3
litellm.request_timeout = float(os.getenv("LLM_TIMEOUT", "360"))
litellm.drop_params = True

dotenv.load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _configured_model() -> LiteLlm:
    """Build the ADK model connector from environment-only configuration.

    ``openai`` lets the course run locally with a standard OpenAI key.
    ``azure`` uses the same ADK agents with an Azure OpenAI deployment. The
    deployment name, not the underlying model family, is the model identifier.
    """
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "azure" if os.getenv("AZURE_OPENAI_ENDPOINT") else "openai"

    if provider == "azure":
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        # Accept the original local variable during the classroom migration.
        # The documented/long-term name remains AZURE_OPENAI_API_KEY.
        api_key = os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        missing = [
            name for name, value in {
                "AZURE_OPENAI_DEPLOYMENT": deployment,
                "AZURE_OPENAI_ENDPOINT": endpoint,
                "AZURE_OPENAI_API_KEY (or temporary OPENAI_API_KEY)": api_key,
            }.items() if not value
        ]
        if missing:
            raise RuntimeError(
                "Azure OpenAI is selected but missing: " + ", ".join(missing)
            )
        os.environ.setdefault("AZURE_API_KEY", api_key or "")
        os.environ.setdefault("AZURE_API_BASE", (endpoint or "").rstrip("/"))
        os.environ.setdefault("AZURE_API_VERSION", api_version)
        return LiteLlm(model=f"azure/{deployment}")

    if provider == "openai":
        model_name = os.getenv("OPENAI_MODEL", "gpt-5-mini")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return LiteLlm(model=f"openai/{model_name}")

    if provider == "ollama":
        model_name = os.getenv("OLLAMA_MODEL", "ornith-1.5:35b")
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        os.environ.setdefault("OPENAI_API_KEY", "ollama")
        os.environ.setdefault("OPENAI_API_BASE", f"{ollama_base}/v1")
        os.environ.setdefault("OLLAMA_KEEP_ALIVE", "60m")
        return LiteLlm(model=f"openai/{model_name}", api_base=f"{ollama_base}/v1", api_key="ollama")

    raise RuntimeError("LLM_PROVIDER must be 'openai', 'azure', or 'ollama'")


MODEL = _configured_model()
