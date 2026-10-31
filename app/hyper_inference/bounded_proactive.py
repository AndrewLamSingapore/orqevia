"""Bounded proactive proposals - proposal only, never execution.

Deterministic, bounded suggestions derived from the request shape. Nothing is
executed, scheduled, or delegated; every proposal requires explicit Owner
approval through the existing authority path.
"""

from __future__ import annotations

import hashlib


SCHEMA = "orqevia.bounded-proactive.v1"
_VERBS = (
    ("verify", "Verify the claim against its owning source before acceptance."),
    ("test", "Add a focused regression test for the changed behavior."),
    ("record", "Record a dated receipt for the outcome and rollback assets."),
    ("observe", "Measure one efficiency dimension before and after the change."),
)


def propose(objective: str, context: str = "", *, limit: int = 3) -> dict:
    """Return at most `limit` proposals; never acts on them."""
    if not isinstance(objective, str) or not objective or not isinstance(context, str):
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "INVALID_INPUT",
            "execution": "FORBIDDEN_WITHOUT_OWNER_APPROVAL",
        }
    if not 1 <= limit <= 4:
        return {
            "schema_version": SCHEMA,
            "ok": False,
            "reason": "INVALID_BOUNDS",
            "execution": "FORBIDDEN_WITHOUT_OWNER_APPROVAL",
        }
    seed = hashlib.sha256((objective + "\n" + context).encode()).hexdigest()
    order = [index for index in range(len(_VERBS))]
    # Deterministic rotation from the input hash; no model call, no side effects.
    start = int(seed[:8], 16) % len(order)
    order = order[start:] + order[:start]
    proposals = []
    for position, index in enumerate(order[:limit]):
        verb, rationale = _VERBS[index]
        proposals.append(
            {
                "id": seed[:12] + "-" + str(position),
                "verb": verb,
                "rationale": rationale,
                "required_approval": True,
                "execution": "FORBIDDEN_WITHOUT_OWNER_APPROVAL",
            }
        )
    return {
        "schema_version": SCHEMA,
        "ok": True,
        "objective_sha256": seed,
        "proposals": proposals,
        "execution": "FORBIDDEN_WITHOUT_OWNER_APPROVAL",
        "authoritative": False,
    }


def capability_summary() -> dict:
    return {
        "schema_version": SCHEMA,
        "status": "QUALIFIED",
        "authority": "PROPOSAL_ONLY",
        "execution_allowed": False,
        "max_proposals": 4,
    }
