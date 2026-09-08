"""Hybrid governed memory retrieval.

Lexical retrieval remains canonical and inspectable. Optional Ollama embeddings
add semantic recall without changing memory authority or persistence contracts.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .memory import MemoryStore
from .settings import SETTINGS, PrimeSettings


class HybridMemory:
    def __init__(self, store: MemoryStore | None = None, settings: PrimeSettings | None = None):
        self.store = store or MemoryStore()
        self.settings = settings or SETTINGS
        self.ollama_url = self.settings.ollama_base_url
        self.embedding_model = self.settings.embedding_model
        self.index_batch = max(1, min(256, int(os.getenv("PRIME_EMBED_INDEX_BATCH", "64"))))
        self.last_status: dict[str, Any] = {"mode": "not_run", "degraded": False, "reason": None}
        with self.store.connect() as db:
            db.execute("""create table if not exists memory_embeddings(
                memory_kind text not null, memory_key text not null, model text not null,
                content_hash text not null, vector_json text not null, dimensions integer not null,
                updated_at text not null, primary key(memory_kind,memory_key,model))""")

    def _embed(self, text: str) -> list[float]:
        from .inference_boundary import deny_legacy_inference
        deny_legacy_inference()

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        return f"{item.get('memory_kind','')} {item.get('memory_key','')} {json.dumps(item.get('value'), sort_keys=True)}"

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _stored_vectors(self) -> dict[tuple[str, str], tuple[str, list[float]]]:
        with self.store.connect() as db:
            rows = db.execute("select memory_kind,memory_key,content_hash,vector_json from memory_embeddings where model=?", (self.embedding_model,)).fetchall()
        return {(row["memory_kind"], row["memory_key"]): (row["content_hash"], json.loads(row["vector_json"])) for row in rows}

    def index_pending(self, *, limit: int | None = None) -> dict[str, Any]:
        candidates = self.store.all_durable(limit=2000)
        stored = self._stored_vectors()
        pending = []
        for item in candidates:
            text = self._text(item); key = (item["memory_kind"], item["memory_key"]); digest = self._hash(text)
            if key not in stored or stored[key][0] != digest:
                pending.append((item, text, digest))
        indexed = 0
        for item, text, digest in pending[: max(1, min(limit or self.index_batch, 256))]:
            vector = self._embed(text)
            if not vector:
                raise RuntimeError("embedding model returned an empty vector")
            with self.store.connect() as db:
                db.execute("""insert into memory_embeddings(memory_kind,memory_key,model,content_hash,vector_json,dimensions,updated_at)
                    values(?,?,?,?,?,?,?) on conflict(memory_kind,memory_key,model) do update set
                    content_hash=excluded.content_hash,vector_json=excluded.vector_json,dimensions=excluded.dimensions,updated_at=excluded.updated_at""",
                    (item["memory_kind"], item["memory_key"], self.embedding_model, digest, json.dumps(vector), len(vector), datetime.now(timezone.utc).isoformat()))
            indexed += 1
        return {"indexed": indexed, "pending": max(0, len(pending) - indexed), "model": self.embedding_model}

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        lexical = self.store.search(query, limit=max(limit * 3, 20))
        try:
            indexing = self.index_pending()
            qv = self._embed(query)
            if not qv:
                raise RuntimeError("embedding model returned an empty vector")
            stored = self._stored_vectors()
            candidates = self.store.all_durable(limit=2000)
            lexical_by_key = {(x["memory_kind"], x["memory_key"]): x for x in lexical}
            reranked = []
            for item in candidates:
                key = (item["memory_kind"], item["memory_key"])
                vector = stored.get(key, ("", []))[1]
                semantic = self._cosine(qv, vector)
                lexical_item = lexical_by_key.get(key, {})
                lexical_score = float(lexical_item.get("retrieval_score") or 0.0)
                confidence = float(item.get("confidence") or 0.0)
                score = (0.55 * semantic) + (0.30 * min(lexical_score / 5.0, 1.0)) + (0.15 * confidence)
                if semantic > 0 or lexical_score > 0:
                    reranked.append((score, {**item, "retrieval_score": lexical_score, "semantic_score": round(semantic, 4), "hybrid_score": round(score, 4), "retrieval_mode": "persistent_hybrid"}))
            reranked.sort(key=lambda pair: pair[0], reverse=True)
            self.last_status = {"mode": "persistent_hybrid", "degraded": False, "reason": None, **indexing, "indexed_vectors": len(stored)}
            return [item for _, item in reranked[:limit]]
        except Exception as exc:
            self.last_status = {"mode": "lexical_fallback", "degraded": True, "reason": type(exc).__name__, "model": self.embedding_model}
            return [{**item, "retrieval_mode": "lexical_fallback"} for item in lexical[:limit]]
