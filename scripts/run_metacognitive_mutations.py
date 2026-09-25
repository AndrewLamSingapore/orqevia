"""Bounded source mutation campaign for consequential metacognitive controls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile


MUTATIONS = {
    "allow_model_fact": ('"model_inference": .35', '"model_inference": 1.0'),
    "allow_assertion_fact": ('"unsupported_assertion": 0.0', '"unsupported_assertion": 1.0'),
    "erase_contradiction": ('if positive and negative:', 'if False and positive and negative:'),
    "create_authority": ('grants_authority=False, may_trigger_consequential_tool=False)', 'grants_authority=True, may_trigger_consequential_tool=True)'),
    "disable_loop_stop": ('len(recent) == 3 and len(set(recent)) == 1', 'False'),
    "ignore_failed_strategy": ('and s.name not in failed', 'and True'),
}


def catches(module, mutation):
    e = module.Evidence
    checks = {
        "allow_model_fact": lambda: (lambda result: result.state == module.EpistemicState.INFERENCE and result.confidence < .5)(module.assess("p", [e("m", "p", True, "model_inference", 1)])),
        "allow_assertion_fact": lambda: module.assess("p", [e("m", "p", True, "unsupported_assertion", 1)]).state == module.EpistemicState.UNKNOWN,
        "erase_contradiction": lambda: module.assess("p", [e("a", "p", True, "primary_record", 1), e("b", "p", False, "primary_record", 2)]).state == module.EpistemicState.CONTRADICTED,
        "create_authority": lambda: not module.assess("p", [e("a", "p", True, "deterministic_tool", 1, True, True)]).grants_authority,
        "disable_loop_stop": lambda: module.should_stop(module.ControlState("x", observations=["x"]*3))[0],
        "ignore_failed_strategy": lambda: module.select_strategy([module.Strategy("failed", frozenset(), 1, 1), module.Strategy("ok", frozenset(), .5, 1)], set(), 2, {"failed"}).name == "ok",
    }
    return not checks[mutation]()


def run(root: Path) -> dict:
    source = (root / "app" / "metacognition.py").read_text(encoding="utf-8")
    rows = []
    with tempfile.TemporaryDirectory(prefix="prime-meta-mutations-") as directory:
        for name, (old, new) in MUTATIONS.items():
            if source.count(old) != 1:
                rows.append({"mutation": name, "detected": False, "error": "mutation_anchor_not_unique"}); continue
            path = Path(directory) / f"{name}.py"
            path.write_text(source.replace(old, new), encoding="utf-8")
            spec = importlib.util.spec_from_file_location(f"mutation_{name}", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            rows.append({"mutation": name, "detected": catches(module, name)})
    detected = sum(row["detected"] for row in rows)
    return {"introduced": len(rows), "detected": detected, "survived": len(rows)-detected,
            "rows": rows, "passed": detected == len(rows)}


if __name__ == "__main__":
    result = run(Path(__file__).resolve().parents[1])
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)
