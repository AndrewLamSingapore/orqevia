"""Evidence-indexed engineering backlog over the existing Phase2 checkpoint store.

Internal candidate adapter, not an authenticated API, scheduler or executor.
Hash-bound observations are still observations, never proof of successful repair.
Only a separately governed production integration may confer execution authority.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from typing import Any

from .phase2_intelligence import AuthorityEnvelope, Phase2Kernel, canonical


SEVERITIES = frozenset(f"P{level}" for level in range(6))
DISPOSITIONS = frozenset({"OPEN", "CANDIDATE_ONLY", "DEFERRED_PHYSICAL", "REQUIRES_AUTHORITY"})
KEY = "engineering_backlog_v1"
HEX = re.compile(r"[0-9a-f]{64}")


def _text(value: Any, name: str, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    return value.strip()


class EngineeringBacklog:
    """Reuse one already-created objective and its CAS/version/event boundaries.

    The caller supplies server-derived authority. This class neither authenticates
    a network caller nor accepts a role from model prose. It is deliberately not
    mounted in production. No transition to VERIFIED/REPAIRED is implemented.
    """

    def __init__(self, store: Phase2Kernel, objective_id: str, authority: AuthorityEnvelope):
        self.store, self.objective_id, self.authority = store, objective_id, authority

    def _current(self):
        if (self.authority.role not in {"OWNER", "SYSTEM", "APPLICATION"}
                or type(self.authority.expires_at) not in {int, float}
                or not math.isfinite(self.authority.expires_at)):
            raise PermissionError("Member/model cannot manage engineering backlog")
        current = self.store.get_objective(self.objective_id, authority=self.authority)
        graph = copy.deepcopy(current["checkpoint"]["problem_graph"])
        if not isinstance(graph, dict):
            raise ValueError("invalid existing problem graph")
        items = graph.setdefault(KEY, {})
        if not isinstance(items, dict):
            raise ValueError("invalid existing engineering backlog")
        # Other internal checkpoint writers exist. Kernel integrity is not a
        # guarantee that their payload satisfies this adapter's state contract.
        if len(items) > 1000:
            raise ValueError("invalid existing engineering backlog")
        for key, item in items.items():
            if (not isinstance(key, str) or not HEX.fullmatch(key)
                    or not isinstance(item, dict) or item.get("id") != key
                    or item.get("severity") not in SEVERITIES
                    or item.get("status") not in DISPOSITIONS
                    or item.get("result") != "UNVERIFIED"
                    or not isinstance(item.get("observations"), list)
                    or not 1 <= len(item["observations"]) <= 100
                    or not isinstance(item.get("dispositions"), list)
                    or len(item["dispositions"]) > 100):
                raise ValueError("invalid existing engineering item state")
            for disposition in item["dispositions"]:
                if not isinstance(disposition, dict) or disposition.get("status") not in DISPOSITIONS:
                    raise ValueError("invalid existing disposition state")
            finding_fields = {"id", "code", "source", "severity", "evidence_ref", "evidence_sha256",
                              "proposed_action", "test", "dependencies"}
            for observation in item["observations"]:
                if (not isinstance(observation, dict)
                        or set(observation) != finding_fields | {"observation_digest", "observed_at", "verification"}
                        or observation.get("verification") != "OBSERVED_BYTES_NOT_REPAIR_VERIFICATION"
                        or observation.get("id") != key
                        or observation.get("severity") not in SEVERITIES
                        or not isinstance(observation.get("evidence_sha256"), str)
                        or not HEX.fullmatch(observation["evidence_sha256"])):
                    raise ValueError("invalid existing observation state")
                finding = {field: observation[field] for field in finding_fields}
                if hashlib.sha256(canonical(finding).encode()).hexdigest() != observation["observation_digest"]:
                    raise ValueError("invalid existing observation digest")
            receipt = item.get("receipt")
            if receipt is not None and (not isinstance(receipt, dict)
                                        or receipt.get("status") not in DISPOSITIONS):
                raise ValueError("invalid existing receipt state")
        return current, graph, items

    def observe(self, *, code: str, source: str, severity: str, evidence_ref: str,
                evidence_bytes: bytes, expected_sha256: str, proposed_action: str,
                test: str, dependencies: list[str] | None = None) -> dict[str, Any]:
        code = _text(code, "finding code", 128)
        source = _text(source, "source")
        evidence_ref = _text(evidence_ref, "evidence reference")
        proposed_action = _text(proposed_action, "proposed action", 2000)
        test = _text(test, "test", 2000)
        if severity not in SEVERITIES:
            raise ValueError("invalid severity")
        if not isinstance(evidence_bytes, bytes) or len(evidence_bytes) > 2_000_000:
            raise ValueError("bounded original evidence bytes required")
        if not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256):
            raise ValueError("invalid expected evidence digest")
        actual = hashlib.sha256(evidence_bytes).hexdigest()
        if actual != expected_sha256:
            raise ValueError("evidence digest mismatch")
        if dependencies is not None and (not isinstance(dependencies, list) or len(dependencies) > 32):
            raise ValueError("invalid dependencies")
        dependencies = sorted({_text(v, "dependency", 128) for v in dependencies or []})
        identity = hashlib.sha256(canonical({"source": source, "code": code}).encode()).hexdigest()
        current, graph, items = self._current()
        prior = items.get(identity)
        finding = {"id": identity, "code": code, "source": source, "severity": severity,
                   "evidence_ref": evidence_ref, "evidence_sha256": actual,
                   "proposed_action": proposed_action, "test": test, "dependencies": dependencies}
        revision = hashlib.sha256(canonical(finding).encode()).hexdigest()
        if prior and any(obs["observation_digest"] == revision for obs in prior["observations"]):
            return {"id": identity, "duplicate": True, "item": copy.deepcopy(prior),
                    "objective_version": current["objective_version"]}
        moment = self.store.clock()
        observation = {**finding, "observation_digest": revision, "observed_at": moment,
                       "verification": "OBSERVED_BYTES_NOT_REPAIR_VERIFICATION"}
        # New evidence reopens work; it cannot inherit an older candidate result.
        history = copy.deepcopy(prior["observations"]) if prior else []
        if len(history) >= 100:
            raise ValueError("observation limit reached; retain history for governed archival")
        history.append(observation)
        if not prior and len(items) >= 1000:
            raise ValueError("backlog item limit reached")
        items[identity] = {"id": identity, "code": code, "source": source,
                           "severity": min(severity, prior["severity"]) if prior else severity,
                           "status": "OPEN", "dependencies": dependencies,
                           "observations": history, "dispositions": copy.deepcopy(prior["dispositions"]) if prior else [],
                           "result": "UNVERIFIED", "receipt": None}
        saved = self.store.checkpoint(self.objective_id, authority=self.authority,
            expected_version=current["objective_version"], updates={"problem_graph": graph},
            next_action="REVIEW_EVIDENCE_BACKLOG")
        return {"id": identity, "duplicate": False, "item": copy.deepcopy(items[identity]),
                "objective_version": saved["objective_version"]}

    def disposition(self, finding_id: str, *, status: str, receipt_ref: str,
                    receipt_bytes: bytes, expected_sha256: str) -> dict[str, Any]:
        if status not in DISPOSITIONS:
            raise ValueError("repair/verification cannot be self-declared by backlog adapter")
        receipt_ref = _text(receipt_ref, "receipt reference")
        if not isinstance(receipt_bytes, bytes) or len(receipt_bytes) > 2_000_000:
            raise ValueError("bounded original receipt bytes required")
        if not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256):
            raise ValueError("invalid receipt digest")
        if hashlib.sha256(receipt_bytes).hexdigest() != expected_sha256:
            raise ValueError("receipt digest mismatch")
        current, graph, items = self._current()
        if finding_id not in items:
            raise KeyError(finding_id)
        item = items[finding_id]
        if len(item["dispositions"]) >= 100:
            raise ValueError("disposition history limit reached")
        receipt = {"reference": receipt_ref, "sha256": expected_sha256, "status": status}
        if item["status"] == status and item["receipt"] == receipt:
            return copy.deepcopy(item)
        item["dispositions"].append({**receipt, "recorded_at": self.store.clock()})
        item.update(status=status, receipt=receipt, result="UNVERIFIED")
        self.store.checkpoint(self.objective_id, authority=self.authority,
            expected_version=current["objective_version"], updates={"problem_graph": graph},
            next_action="REVIEW_EVIDENCE_BACKLOG")
        return copy.deepcopy(item)

    def snapshot(self) -> dict[str, Any]:
        current, _, items = self._current()
        ordered = sorted(items.values(), key=lambda item: (item["severity"], item["id"]))
        return {"objective_id": self.objective_id, "objective_version": current["objective_version"],
                "objective_state": current["state"], "backlog_depth": len(ordered),
                "unresolved_critical_count": sum(i["severity"] in {"P0", "P1"} for i in ordered),
                "items": copy.deepcopy(ordered), "engineering_loop": "UNMOUNTED_CANDIDATE_ADAPTER",
                "continuous_improvement": "NOT_ESTABLISHED",
                "quiet_steady_state_qualified": False,
                "execution_authority": False,
                "scope": "Persistent evidence-indexed backlog only; not daemon, executor, repair or production acceptance"}
