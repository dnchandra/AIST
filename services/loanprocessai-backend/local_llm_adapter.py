"""Local LLM and Embedding adapter for LoanProcessAI.

Uses local Ollama endpoints:
- LLM: ornith-1.5:35b (35B reasoning/chat, pinned via OLLAMA_MODEL)
- Embeddings: embeddinggemma-2:740m (768 dimensions)

Provides drop-in compatibility with OpenAI SDK and emits identical telemetry metadata
so observability.py and evaluator.py continue working without modification.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("loanprocessai")

DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_LLM_MODEL = os.getenv("OLLAMA_MODEL", "ornith-1.5:35b")
DEFAULT_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "embeddinggemma-2:740m")


def get_embedding(
    text: str,
    model: str = DEFAULT_EMBEDDING_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
) -> List[float]:
    """Generate embedding vector using local Ollama embeddinggemma-2:740m (768 dims)."""
    url = f"{base_url}/api/embeddings"
    payload = {"model": model, "prompt": text, "keep_alive": "60m"}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    timeout = int(os.getenv("EMBEDDING_TIMEOUT", "120"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            embedding = body.get("embedding")
            if not embedding or not isinstance(embedding, list):
                raise ValueError(f"Unexpected embedding response from Ollama: {body}")
            return embedding
    except Exception as exc:
        logger.error(f"Failed to generate embedding from Ollama model '{model}': {exc}")
        raise RuntimeError(f"Ollama embedding failed ({model}): {exc}") from exc


def call_ollama_chat(
    prompt: str,
    system_instruction: str = "You are LoanAssist. Answer with grounded evidence from the supplied context.",
    model: str = DEFAULT_LLM_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    max_tokens: Optional[int] = 1024,
) -> Tuple[str, float, Dict[str, Any]]:
    """Execute chat completion against local Ollama OpenAI-compatible endpoint.

    Returns:
        (answer_text, latency_ms, llm_metadata_dict)
    """
    url = f"{base_url}/v1/chat/completions"
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "keep_alive": "60m",
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
        method="POST",
    )

    timeout = int(os.getenv("LLM_TIMEOUT", "300"))
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.error(f"Ollama chat completion failed for model '{model}': {exc}")
        raise RuntimeError(f"Ollama chat completion failed: {exc}") from exc

    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"Empty completion choices returned by Ollama: {body}")

    msg = choices[0].get("message", {})
    answer = msg.get("content") or ""

    # Usage metadata for enterprise telemetry
    usage = body.get("usage", {})
    metadata = {
        "input_tokens": usage.get("prompt_tokens", len(prompt) // 4),
        "output_tokens": usage.get("completion_tokens", len(answer) // 4),
        "total_tokens": usage.get("total_tokens", (len(prompt) + len(answer)) // 4),
        "finish_reason": choices[0].get("finish_reason", "stop"),
        "llm_response_id": body.get("id", f"ollama-{int(time.time())}"),
        "llm_response_model": body.get("model", model),
    }

    return answer, latency_ms, metadata
