import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.portal_integration import build_experiment_spec, validate_experiment_candidate, validate_experiment_spec

candidate = json.loads((ROOT / "contracts/examples/portal-aquarium-candidate.json").read_text())
expected = json.loads((ROOT / "contracts/examples/expected-experiment-spec.json").read_text())
candidate = validate_experiment_candidate(candidate)
spec = validate_experiment_spec(build_experiment_spec(candidate))
assert spec["candidate_id"] == expected["candidate_id"]
assert spec["target_system"] == expected["target_system"]
assert spec["approval_state"] == expected["approval_state"]
assert spec["verification"]["verdict"] == expected["verification_verdict"]
assert spec["approval_state"] != "approved"
print(json.dumps(spec, indent=2))
