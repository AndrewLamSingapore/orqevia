"""Access-controlled retrieval grounding for ORQEVIA.

Retrieved passages are treated as untrusted data, never as instructions.
Every returned passage carries ``content_is_authority=false`` and a citation
that resolves to the exact document/chunk. Access controls are applied before
any passage can enter a prompt, and deleted or superseded documents are
excluded from retrieval, caches and citations.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .geospatial import haversine_km, validate_coordinate


@dataclass(frozen=True)
class Passage:
    doc_id: str
    chunk_index: int
    text: str
    source: str
    authority_class: str
    scope: str
    doc_version: int
    geometry: dict | None
    observed_at: str | None


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _chunks(text: str, max_chars: int = 1600) -> list[str]:
    text = text.strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            out.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        out.append(current.strip())
    return out


class DocumentStore:
    """Versioned, access-controlled document/chunk store."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._passages: dict[tuple[str, int], Passage] = {}
        self._cache: dict[tuple, tuple[float, tuple[str, ...]]] = {}

    def ingest(
        self,
        *,
        doc_id: str,
        text: str,
        source: str,
        authority_class: str,
        scope: str,
        geometry: dict | None = None,
        observed_at: str | None = None,
        version: int = 1,
    ) -> list[Passage]:
        if not text.strip():
            raise ValueError("document text must not be empty")
        if scope not in {"OWNER_PRIVATE", "MEMBER_PRIVATE", "HOUSEHOLD_SHARED", "APPLICATION", "SYSTEM"}:
            raise ValueError("unknown document scope")
        old_version = self._docs.get(doc_id, {}).get("version")
        if old_version is not None and version <= old_version:
            raise ValueError("document version must increase monotonically")
        # Remove superseded chunks so older passages can never resurface.
        if old_version is not None:
            self.delete(doc_id)
        self._docs[doc_id] = {
            "source": source,
            "authority_class": authority_class,
            "scope": scope,
            "version": version,
            "geometry": geometry,
            "observed_at": observed_at,
            "content_sha256": _sha(text),
        }
        passages: list[Passage] = []
        for index, chunk in enumerate(_chunks(text)):
            passage = Passage(
                doc_id=doc_id,
                chunk_index=index,
                text=chunk,
                source=source,
                authority_class=authority_class,
                scope=scope,
                doc_version=version,
                geometry=geometry,
                observed_at=observed_at,
            )
            self._passages[(doc_id, index)] = passage
            passages.append(passage)
        self._cache.clear()
        return passages

    def delete(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)
        for key in [key for key in self._passages if key[0] == doc_id]:
            self._passages.pop(key, None)
        self._cache.clear()

    def contains(self, doc_id: str) -> bool:
        return doc_id in self._docs

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "docs": self._docs,
            "passages": [
                {
                    "doc_id": p.doc_id,
                    "chunk_index": p.chunk_index,
                    "text": p.text,
                    "source": p.source,
                    "authority_class": p.authority_class,
                    "scope": p.scope,
                    "doc_version": p.doc_version,
                    "geometry": p.geometry,
                    "observed_at": p.observed_at,
                }
                for p in self._passages.values()
            ],
        }
        Path(path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "DocumentStore":
        store = cls()
        source = Path(path)
        if not source.exists():
            return store
        payload = json.loads(source.read_text(encoding="utf-8"))
        for doc_id, doc in payload.get("docs", {}).items():
            store._docs[doc_id] = doc
        for item in payload.get("passages", []):
            key = (item["doc_id"], item["chunk_index"])
            store._passages[key] = Passage(**item)
        return store

    def _visible(self, actor_scopes: set[str]) -> list[Passage]:
        return [p for p in self._passages.values() if p.scope in actor_scopes]

    @staticmethod
    def _score(query: str, passage: Passage) -> float:
        terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        if not terms:
            return 0.0
        body = passage.text.lower()
        return sum(body.count(term) for term in terms) / max(1.0, math.log(len(body) + 2))

    def retrieve(
        self,
        query: str,
        *,
        actor_scopes: set[str],
        limit: int = 5,
        near: tuple[float, float] | None = None,
        radius_km: float | None = None,
        min_time: str | None = None,
        max_time: str | None = None,
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be positive")
        candidates = self._visible(actor_scopes)
        if near is not None:
            lat, lon = validate_coordinate(*near)
            candidates = [
                p
                for p in candidates
                if p.geometry and p.geometry.get("type") == "Point"
                and (radius_km is None or haversine_km(lat, lon, float(p.geometry["coordinates"][1]), float(p.geometry["coordinates"][0])) <= radius_km)
            ]
        if min_time is not None or max_time is not None:
            candidates = [
                p
                for p in candidates
                if p.observed_at is None
                or (min_time is None or p.observed_at >= min_time)
                and (max_time is None or p.observed_at <= max_time)
            ]
        scored = sorted(((self._score(query, p), p) for p in candidates), key=lambda pair: -pair[0])
        results = []
        for score, passage in scored[:limit]:
            if score <= 0:
                continue
            results.append(
                {
                    "doc_id": passage.doc_id,
                    "chunk_index": passage.chunk_index,
                    "passage": passage.text,
                    "citation": f"{passage.source}#{passage.doc_id}:chunk-{passage.chunk_index}",
                    "source": passage.source,
                    "authority_class": passage.authority_class,
                    "doc_version": passage.doc_version,
                    "observed_at": passage.observed_at,
                    "content_is_authority": False,
                    "instructions_may_execute": False,
                }
            )
        if not results:
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "results": [],
                "explanation": "No accessible, non-deleted source supports the query under the current access scope.",
            }
        return {"status": "GROUNDED", "results": results}

    def citations(self) -> list[str]:
        return sorted({p.source for p in self._passages.values()})
