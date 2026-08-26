import json
from pathlib import Path

from app.portal_integration import build_experiment_spec, validate_experiment_candidate, validate_experiment_spec

candidate = json.loads(Path("contracts/examples/portal-aquarium-candidate.json").read_text())
expected = json.loads(Path("contracts/examples/expected-experiment-spec.json").read_text())
candidate = validate_experiment_candidate(candidate)
spec = validate_experiment_spec(build_experiment_spec(candidate))
assert spec["candidate_id"] == expected["candidate_id"]
assert spec["target_system"] == expected["target_system"]
assert spec["approval_state"] == expected["approval_state"]
assert spec["verification"]["verdict"] == expected["verification_verdict"]
assert spec["approval_state"] != "approved"
print(json.dumps(spec, indent=2))
