"""Local Elasticsearch 9.5.5 / 8.x adapter for Hybrid RAG Retrieval + Neural Reranking.

Combines:
- Elasticsearch 9.5.5 native Retriever API (Reciprocal Rank Fusion - RRF)
  combining BM25 text match and HNSW dense vector cosine similarity (embeddinggemma-2:740m).
- Automatic graceful fallback to top-level bool + kNN hybrid search on basic licenses.
- In-process CPU neural reranking (FlashRank ms-marco-TinyBERT-L-2-v2 by default,
  ms-marco-MiniLM-L-12-v2 challenger, or Nemotron-1B for batch).

Zero GPU VRAM impact: ensures ornith-1.5:35b (20.7GB) + embeddinggemma-2:740m (0.46GB)
remain 100% pinned in RTX 5090 VRAM.

Returns chunk structures 100% compatible with Azure AI Search output.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import sys as _sys
from pathlib import Path as _Path

# Flat backend layout: backend/ must be on sys.path (uvicorn --app-dir backend,
# or scripts insert backend). Self-heal for `python backend/app.py` edge case.
if str(_Path(__file__).resolve().parent) not in _sys.path:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
from local_llm_adapter import get_embedding  # noqa: E402

logger = logging.getLogger("loanprocessai")

DEFAULT_ES_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200").rstrip("/")
DEFAULT_INDEX = os.getenv("ELASTICSEARCH_INDEX", "loanprocessai-rag")
DEFAULT_CANDIDATE_K = int(os.getenv("RAG_CANDIDATE_K", "25"))
DEFAULT_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
DEFAULT_RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
DEFAULT_RERANKER_MODEL = os.getenv("RERANKER_MODEL", "ms-marco-TinyBERT-L-2-v2").strip()

_FLASHRANK_CACHE: Dict[str, Any] = {}
_NEMOTRON_CACHE: Dict[str, Any] = {}
_TRIAL_ACTIVATED = False


def _ensure_es_trial(es_url: str) -> None:
    """Attempt activating 30-day trial license once if running on basic license."""
    global _TRIAL_ACTIVATED
    if _TRIAL_ACTIVATED:
        return
    try:
        req = urllib.request.Request(
            f"{es_url}/_license/start_trial?acknowledge=true",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("acknowledged"):
                logger.info("Elasticsearch Platinum trial license activated for native RRF.")
        _TRIAL_ACTIVATED = True
    except Exception:
        _TRIAL_ACTIVATED = True


def _rerank_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: int,
    model_name: str = "ms-marco-TinyBERT-L-2-v2",
) -> Tuple[List[Dict[str, Any]], float]:
    """Rerank candidates on CPU using FlashRank or Nemotron-1B ONNX.

    Zero GPU VRAM impact.
    """
    if not chunks:
        return [], 0.0

    t0 = time.perf_counter()

    # Case A: FlashRank models (ms-marco-TinyBERT-L-2-v2, ms-marco-MiniLM-L-12-v2)
    if "nemotron" not in model_name.lower():
        try:
            from flashrank import Ranker, RerankRequest

            if model_name not in _FLASHRANK_CACHE:
                logger.info(f"Loading FlashRank model '{model_name}' on CPU...")
                _FLASHRANK_CACHE[model_name] = Ranker(model_name=model_name)

            ranker = _FLASHRANK_CACHE[model_name]
            passages = [
                {
                    "id": i,
                    "text": c.get("chunk", "") or c.get("title", ""),
                }
                for i, c in enumerate(chunks)
            ]
            req = RerankRequest(query=query, passages=passages)
            results = ranker.rerank(req)

            reranked: List[Dict[str, Any]] = []
            for item in results[:top_k]:
                idx = item["id"]
                original = chunks[idx]
                r_score = float(item.get("score", 0.0))
                chunk_copy = dict(original)
                chunk_copy["es_score"] = original.get("score", 0.0)
                chunk_copy["rerank_score"] = r_score
                chunk_copy["score"] = r_score
                chunk_copy["@search.score"] = r_score
                chunk_copy["@search.rerankerScore"] = r_score
                reranked.append(chunk_copy)

            rerank_lat_ms = (time.perf_counter() - t0) * 1000
            return reranked, rerank_lat_ms
        except Exception as exc:
            logger.warning(f"FlashRank reranking failed with '{model_name}': {exc}. Returning raw ES order.")
            return chunks[:top_k], (time.perf_counter() - t0) * 1000

    # Case B: Nemotron-1B INT4 ONNX (overnight/async batch credit memos)
    else:
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer

            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_dir = os.path.join(base_dir, ".models", "nemotron_rerank_1b_onnx")
            if not os.path.isdir(model_dir):
                logger.warning(f"Nemotron model dir not found at '{model_dir}'. Returning raw ES order.")
                return chunks[:top_k], (time.perf_counter() - t0) * 1000

            if "session" not in _NEMOTRON_CACHE:
                tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
                tokenizer.enable_truncation(max_length=512)
                sess_opts = ort.SessionOptions()
                sess_opts.intra_op_num_threads = 4
                session = ort.InferenceSession(
                    os.path.join(model_dir, "model_int4_full.onnx"),
                    sess_options=sess_opts,
                    providers=["CPUExecutionProvider"],
                )
                _NEMOTRON_CACHE["tokenizer"] = tokenizer
                _NEMOTRON_CACHE["session"] = session

            tokenizer = _NEMOTRON_CACHE["tokenizer"]
            session = _NEMOTRON_CACHE["session"]

            scored = []
            for c in chunks:
                text = c.get("chunk", "") or c.get("title", "")
                enc = tokenizer.encode(query, text)
                input_ids = np.array([enc.ids], dtype=np.int64)
                attn_mask = np.array([enc.attention_mask], dtype=np.int64)
                out = session.run(None, {"input_ids": input_ids, "attention_mask": attn_mask})
                rel_score = float(np.asarray(out[0])[0][0])
                chunk_copy = dict(c)
                chunk_copy["es_score"] = c.get("score", 0.0)
                chunk_copy["rerank_score"] = rel_score
                chunk_copy["score"] = rel_score
                chunk_copy["@search.score"] = rel_score
                scored.append(chunk_copy)

            scored.sort(key=lambda x: x["rerank_score"], reverse=True)
            rerank_lat_ms = (time.perf_counter() - t0) * 1000
            return scored[:top_k], rerank_lat_ms
        except Exception as exc:
            logger.warning(f"Nemotron reranking failed: {exc}. Returning raw ES order.")
            return chunks[:top_k], (time.perf_counter() - t0) * 1000


def search_elasticsearch_chunks(
    question: str,
    top_k: int = DEFAULT_TOP_K,
    es_url: str = DEFAULT_ES_URL,
    index_name: str = DEFAULT_INDEX,
    candidate_k: Optional[int] = None,
    reranker_enabled: Optional[bool] = None,
    reranker_model: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], float]:
    """Execute hybrid BM25 + kNN search on Elasticsearch, then rerank on CPU.

    1. Native Elasticsearch 9.5.5 Retriever API with Reciprocal Rank Fusion (RRF)
       combines BM25 and HNSW vector search to fetch candidate_k (default 25) docs.
    2. Fallback to 8.x top-level bool + knn if license/API requires.
    3. FlashRank CPU neural reranker refines candidate_k down to top_k (default 5).

    Returns:
        (chunks_list, search_latency_ms)
    """
    started = time.perf_counter()

    if candidate_k is None:
        candidate_k = DEFAULT_CANDIDATE_K
    if reranker_enabled is None:
        reranker_enabled = DEFAULT_RERANKER_ENABLED
    if reranker_model is None:
        reranker_model = DEFAULT_RERANKER_MODEL

    # Ensure retrieval size is sufficient for reranking
    retrieval_k = candidate_k if reranker_enabled else top_k

    # Step 1: Compute query embedding with local model
    try:
        query_vector = get_embedding(question)
    except Exception as exc:
        logger.warning(f"Could not generate embedding for query '{question[:50]}': {exc}. Falling back to BM25 only.")
        query_vector = None

    # Step 2: Build Elasticsearch 9.5.5 Native Retriever (RRF) query
    retrievers: List[Dict[str, Any]] = [
        {
            "standard": {
                "query": {
                    "bool": {
                        "should": [
                            {
                                "match": {
                                    "chunk": {
                                        "query": question,
                                        "boost": 0.5,
                                    }
                                }
                            },
                            {
                                "match": {
                                    "title": {
                                        "query": question,
                                        "boost": 0.3,
                                    }
                                }
                            },
                        ]
                    }
                }
            }
        }
    ]

    if query_vector:
        retrievers.append({
            "knn": {
                "field": "text_vector",
                "query_vector": query_vector,
                "k": retrieval_k,
                "num_candidates": max(50, retrieval_k * 2),
            }
        })

    if len(retrievers) >= 2:
        rrf_query: Dict[str, Any] = {
            "retriever": {
                "rrf": {
                    "retrievers": retrievers,
                    "rank_window_size": max(retrieval_k, 25),
                    "rank_constant": 60,
                }
            },
            "size": retrieval_k,
        }
    else:
        # Graceful single retriever: when vector is unavailable, use standard BM25 retriever directly
        rrf_query = {
            "retriever": retrievers[0],
            "size": retrieval_k,
        }

    # Fallback query for ES 8.x or Basic license
    fallback_query: Dict[str, Any] = {
        "size": retrieval_k,
        "query": {
            "bool": {
                "should": [
                    {
                        "match": {
                            "chunk": {
                                "query": question,
                                "boost": 0.5,
                            }
                        }
                    },
                    {
                        "match": {
                            "title": {
                                "query": question,
                                "boost": 0.3,
                            }
                        }
                    },
                ]
            }
        },
    }
    if query_vector:
        fallback_query["knn"] = {
            "field": "text_vector",
            "query_vector": query_vector,
            "k": retrieval_k,
            "num_candidates": max(50, retrieval_k * 2),
            "boost": 1.0,
        }

    search_url = f"{es_url}/{index_name}/_search"
    res_payload = None

    # Attempt 1: Native ES 9.5.5 Retriever RRF (with 1 retry on connection reset)
    for attempt in range(2):
        try:
            req_data = json.dumps(rrf_query).encode("utf-8")
            req = urllib.request.Request(
                search_url,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            logger.info(f"Retriever query fallback to bool+knn (HTTP {exc.code}): {err_body[:100]}")
            # Attempt 2: Fallback query
            req_data = json.dumps(fallback_query).encode("utf-8")
            req = urllib.request.Request(
                search_url,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_payload = json.loads(resp.read().decode("utf-8"))
                break
            except Exception as fallback_exc:
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.error(f"Elasticsearch fallback query failed: {fallback_exc}")
                raise RuntimeError(f"Elasticsearch query failed: {fallback_exc}") from fallback_exc
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.5)
                continue
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.error(f"Elasticsearch connection error to '{es_url}': {exc}")
            raise RuntimeError(f"Elasticsearch unreachable: {exc}") from exc

    hits = res_payload.get("hits", {}).get("hits", []) if res_payload else []
    candidate_chunks: List[Dict[str, Any]] = []

    for hit in hits:
        source = hit.get("_source", {})
        score = hit.get("_score", 0.0)
        candidate_chunks.append({
            "chunk_id": source.get("chunk_id", hit.get("_id")),
            "parent_id": source.get("parent_id", ""),
            "title": source.get("title", "Credit Policy Reference"),
            "chunk": source.get("chunk", ""),
            "score": score,
            "@search.score": score,  # Compatibility with Azure AI Search field
            "es_score": score,
        })

    # Step 3: Neural Reranking on CPU (if enabled)
    if reranker_enabled and candidate_chunks:
        final_chunks, _ = _rerank_chunks(
            query=question,
            chunks=candidate_chunks,
            top_k=top_k,
            model_name=reranker_model,
        )
    else:
        final_chunks = candidate_chunks[:top_k]

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return final_chunks, latency_ms
