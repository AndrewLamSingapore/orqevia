"""Hybrid governed memory retrieval.

Lexical retrieval remains canonical and inspectable. Optional Ollama embeddings
add semantic recall without changing memory authority or persistence contracts.
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from typing import Any

from .memory import MemoryStore


class HybridMemory:
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
        self.embedding_model = os.getenv("PRIME_EMBEDDING_MODEL", "nomic-embed-text")

    def _embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.embedding_model, "input": text}).encode("utf-8")
        request = urllib.request.Request(f"{self.ollama_url}/api/embed", data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        embeddings = data.get("embeddings") or []
        return [float(x) for x in embeddings[0]] if embeddings else []

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        lexical = self.store.search(query, limit=max(limit * 3, 20))
        if not lexical:
            return []
        try:
            qv = self._embed(query)
            if not qv:
                return lexical[:limit]
            reranked = []
            for item in lexical:
                value = json.dumps(item.get("value"), sort_keys=True)
                text = f"{item.get('memory_kind','')} {item.get('memory_key','')} {value}"
                semantic = self._cosine(qv, self._embed(text))
                lexical_score = float(item.get("retrieval_score") or 0.0)
                confidence = float(item.get("confidence") or 0.0)
                score = (0.55 * semantic) + (0.30 * min(lexical_score / 5.0, 1.0)) + (0.15 * confidence)
                reranked.append((score, {**item, "semantic_score": round(semantic, 4), "hybrid_score": round(score, 4)}))
            reranked.sort(key=lambda pair: pair[0], reverse=True)
            return [item for _, item in reranked[:limit]]
        except Exception:
            return lexical[:limit]
