"""
AIST Local Hybrid RAG Engine (Vector Embedding + Okapi BM25)
Utilizes RTX 5090 via Ollama (embeddinggemma-2:740m, 768-dim) and BM25 keyword scoring.
Indexes Markdown runbooks from ai-triage/knowledge-base/runbooks/*.md with persistent caching.
"""

import os
import re
import math
import json
import hashlib
import logging
from typing import List, Dict, Any, Optional
import requests

from config import OLLAMA_HOST, EMBEDDING_LLM

logger = logging.getLogger("aist_rag_engine")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNBOOKS_DIR = os.path.join(CURRENT_DIR, "runbooks")
CACHE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", "..", "data"))
CACHE_FILE = os.path.join(CACHE_DIR, "runbooks_vector_cache.json")


def _tokenize(text: str) -> List[str]:
    """Tokenize and normalize text into alphanumeric words."""
    return re.findall(r"\w+", text.lower())


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1))
    norm_b = math.sqrt(sum(b * b for b in vec2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class HybridRAGEngine:
    """
    Enterprise SRE Runbook Retrieval Engine.
    Combines dense neural embeddings (embeddinggemma-2:740m) with sparse BM25 scoring.
    """

    def __init__(self, runbooks_dir: str = RUNBOOKS_DIR, ollama_url: str = OLLAMA_HOST, model: str = EMBEDDING_LLM):
        self.runbooks_dir = runbooks_dir
        self.ollama_url = ollama_url
        self.model = model
        self.documents: List[Dict[str, Any]] = []
        self.bm25_idf: Dict[str, float] = {}
        self.avg_doc_len: float = 0.0
        self.is_indexed: bool = False
        self._initialize_index()

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Fetch 768-dim vector embedding from local Ollama host."""
        try:
            r = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.model, "prompt": text[:2000]},
                timeout=5
            )
            if r.status_code == 200:
                return r.json().get("embedding", [])
        except Exception as e:
            logger.debug(f"Failed to fetch embedding from {self.ollama_url}: {e}")
        return None

    def _parse_runbook_markdown(self, filepath: str) -> Dict[str, Any]:
        """Parse structured sections and metadata from markdown runbook."""
        with open(filepath, "r", encoding="utf-8") as f:
            raw_content = f.read()

        basename = os.path.basename(filepath)
        runbook_id = basename.split("_")[0] if "_" in basename else basename.replace(".md", "")

        # Extract Title
        title_match = re.search(r"^#\s+(.+)$", raw_content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else basename

        # Extract Severity
        sev_match = re.search(r"\*\*Severity\*\*:\s*([^\n\r]+)", raw_content, re.IGNORECASE) or re.search(r"## Severity:\s*([^\n\r]+)", raw_content, re.IGNORECASE)
        severity = sev_match.group(1).strip() if sev_match else "UNKNOWN"

        # Extract Triggers
        triggers_match = re.search(r"\*\*Alert Triggers\*\*:\s*([^\n\r]+)", raw_content, re.IGNORECASE)
        triggers = triggers_match.group(1).strip() if triggers_match else ""

        # Extract Remediation Steps summary
        remediation_match = re.search(r"###\s*3\.\s*Remediation Actions[\s\S]*?(?=(?:^###|\Z))", raw_content, re.MULTILINE)
        remediation_text = remediation_match.group(0).strip() if remediation_match else ""

        return {
            "id": runbook_id,
            "filename": basename,
            "title": title,
            "severity": severity,
            "triggers": triggers,
            "remediation_summary": remediation_text,
            "content": raw_content,
            "mtime": os.path.getmtime(filepath)
        }

    def _build_bm25_index(self):
        """Precompute BM25 inverted index and document length statistics."""
        num_docs = len(self.documents)
        if num_docs == 0:
            return

        doc_lengths = []
        term_doc_counts: Dict[str, int] = {}

        for doc in self.documents:
            tokens = set(_tokenize(f"{doc['title']} {doc['triggers']} {doc['content']}"))
            doc["token_list"] = _tokenize(f"{doc['title']} {doc['triggers']} {doc['content']}")
            doc_lengths.append(len(doc["token_list"]))
            for t in tokens:
                term_doc_counts[t] = term_doc_counts.get(t, 0) + 1

        self.avg_doc_len = sum(doc_lengths) / num_docs if num_docs > 0 else 1.0

        # BM25 IDF formulation: log((N - n + 0.5) / (n + 0.5) + 1)
        self.bm25_idf = {}
        for term, n in term_doc_counts.items():
            self.bm25_idf[term] = math.log(((num_docs - n + 0.5) / (n + 0.5)) + 1.0)

    def _score_bm25(self, query_tokens: List[str], doc: Dict[str, Any], k1: float = 1.5, b: float = 0.75) -> float:
        """Compute BM25 relevance score for a document."""
        doc_tokens = doc.get("token_list", [])
        doc_len = len(doc_tokens)
        if doc_len == 0:
            return 0.0

        tf_map: Dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        score = 0.0
        for qt in query_tokens:
            if qt not in tf_map:
                continue
            tf = tf_map[qt]
            idf = self.bm25_idf.get(qt, 0.1)
            num = tf * (k1 + 1.0)
            denom = tf + k1 * (1.0 - b + b * (doc_len / self.avg_doc_len))
            score += idf * (num / denom)
        return score

    def _initialize_index(self):
        """Load, parse, and generate embeddings for all markdown runbooks."""
        if not os.path.exists(self.runbooks_dir):
            logger.warning(f"Runbooks directory not found: {self.runbooks_dir}")
            return

        os.makedirs(CACHE_DIR, exist_ok=True)
        cached_data = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
            except Exception:
                cached_data = {}

        self.documents = []
        cache_updated = False

        md_files = [f for f in os.listdir(self.runbooks_dir) if f.endswith(".md")]
        for f in md_files:
            path = os.path.join(self.runbooks_dir, f)
            doc = self._parse_runbook_markdown(path)
            
            # Check if cached embedding is fresh
            cache_entry = cached_data.get(f)
            if cache_entry and cache_entry.get("mtime") == doc["mtime"] and "embedding" in cache_entry:
                doc["embedding"] = cache_entry["embedding"]
            else:
                # Generate new embedding
                emb_text = f"{doc['title']}\nTriggers: {doc['triggers']}\n{doc['content'][:1500]}"
                emb = self._get_embedding(emb_text)
                if emb:
                    doc["embedding"] = emb
                    cached_data[f] = {
                        "mtime": doc["mtime"],
                        "embedding": emb
                    }
                    cache_updated = True

            self.documents.append(doc)

        if cache_updated:
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cached_data, f)
            except Exception as e:
                logger.warning(f"Could not write RAG cache file: {e}")

        self._build_bm25_index()
        self.is_indexed = True
        logger.info(f"Hybrid RAG Engine initialized with {len(self.documents)} runbooks.")

    def search(self, query: str, k: int = 3, vector_weight: float = 0.6) -> List[Dict[str, Any]]:
        """
        Execute Hybrid Retrieval combining Cosine Vector Similarity and Okapi BM25.
        Returns top-k ranked documents with similarity scores and remediation excerpts.
        """
        if not self.documents:
            return []

        query_tokens = _tokenize(query)
        query_emb = self._get_embedding(query)

        scored_docs = []
        bm25_scores = []
        cos_scores = []

        for doc in self.documents:
            b_score = self._score_bm25(query_tokens, doc)
            c_score = 0.0
            if query_emb and "embedding" in doc:
                c_score = max(0.0, _cosine_similarity(query_emb, doc["embedding"]))
            
            bm25_scores.append(b_score)
            cos_scores.append(c_score)

        # Min-max normalization for fusion
        max_bm25 = max(bm25_scores) if bm25_scores and max(bm25_scores) > 0 else 1.0
        min_bm25 = min(bm25_scores) if bm25_scores else 0.0
        range_bm25 = (max_bm25 - min_bm25) if (max_bm25 - min_bm25) > 0 else 1.0

        for idx, doc in enumerate(self.documents):
            norm_bm25 = (bm25_scores[idx] - min_bm25) / range_bm25
            norm_cos = cos_scores[idx]

            # If embedding was unavailable, rely 100% on BM25
            if not query_emb:
                final_score = norm_bm25
            else:
                final_score = (vector_weight * norm_cos) + ((1.0 - vector_weight) * norm_bm25)

            scored_docs.append({
                "id": doc["id"],
                "filename": doc["filename"],
                "title": doc["title"],
                "severity": doc["severity"],
                "triggers": doc["triggers"],
                "match_score": round(final_score, 4),
                "vector_sim": round(norm_cos, 4),
                "bm25_score": round(norm_bm25, 4),
                "remediation_summary": doc.get("remediation_summary", ""),
                "content": doc["content"]
            })

        # Rank by final score descending
        scored_docs.sort(key=lambda x: x["match_score"], reverse=True)
        return scored_docs[:k]


# Global Singleton Engine Instance
_rag_engine_instance: Optional[HybridRAGEngine] = None

def get_rag_engine() -> HybridRAGEngine:
    global _rag_engine_instance
    if _rag_engine_instance is None:
        _rag_engine_instance = HybridRAGEngine()
    return _rag_engine_instance

