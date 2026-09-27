"""Independent deterministic verifier for the metacognitive control kernel."""
from __future__ import annotations

import json
from app.metacognition import Evidence, EpistemicState, Strategy, assess, select_strategy


def verify() -> dict:
    attacks = {
        "unsupported_assertion_not_fact": assess("x", [Evidence("fake", "x", True, "unsupported_assertion", 1)]).state != EpistemicState.VERIFIED_FACT,
        "contradiction_preserved": assess("x", [Evidence("a", "x", True, "primary_record", 1), Evidence("b", "x", False, "primary_record", 2)]).state == EpistemicState.CONTRADICTED,
        "no_evidence_unknown": assess("x", []).state == EpistemicState.UNKNOWN,
        "reasoning_no_authority": not assess("x", [Evidence("a", "x", True, "deterministic_tool", 1, True, True)]).grants_authority,
        "failed_strategy_abandoned": select_strategy([Strategy("failed", frozenset(), 1, 1), Strategy("alternate", frozenset(), .5, 1)], set(), 2, {"failed"}).name == "alternate",
    }
    return {"verifier": "deterministic-independent-metacognition-v1", "independent": True,
            "checks": attacks, "passed": all(attacks.values())}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
