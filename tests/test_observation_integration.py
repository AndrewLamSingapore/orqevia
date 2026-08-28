import unittest

from app.observation_integration import build_portal_result, validate_velyqua_event


APPROVAL = {
    "owner_id": "owner-1",
    "approved_at": "2026-08-28T03:00:00Z",
    "scope": "observation_only",
    "provenance": ["owner-confirmation:ui"],
}


def execution(state, operation):
    approval = APPROVAL if state in {"approved_for_observation", "collecting_evidence", "completed"} else None
    payload = {
        "experiment_id": "PRM-EXP-ABC123",
        "candidate_id": "PTL-EXP-ABC123",
        "state": state,
        "objective": "Collect bounded observations.",
        "evidence_requirements": ["Attributed observation"],
        "owner_approval": approval,
        "created_at": "2026-08-28T02:55:00Z",
    }
    return validate_velyqua_event({
        "schema_version": "1.0",
        "operation_id": operation,
        "account_id": "owner-1",
        "aggregate_type": "experiment_execution",
        "aggregate_id": payload["experiment_id"],
        "event_type": f"experiment_execution.{state}",
        "payload": payload,
        "occurred_at": "2026-08-28T03:00:00Z",
    })


def observation():
    payload = {
        "schema_version": "1.0",
        "observation_id": "VLY-OBS-ABC123",
        "source": "velyqua",
        "experiment_id": "PRM-EXP-ABC123",
        "tank_id": "tank-1",
        "observed_at": "2026-08-28T03:05:00Z",
        "kind": "sensor",
        "metric": "temperature",
        "value": 27.1,
        "unit": "C",
        "evidence_level": "raw",
        "provenance": ["edge-node:temperature-probe"],
        "notes": None,
    }
    return validate_velyqua_event({
        "schema_version": "1.0",
        "operation_id": "integration:owner-1:observation:VLY-OBS-ABC123",
        "account_id": "owner-1",
        "aggregate_type": "observation",
        "aggregate_id": payload["observation_id"],
        "event_type": "observation.recorded",
        "payload": payload,
        "occurred_at": payload["observed_at"],
    })


class ObservationIntegrationTests(unittest.TestCase):
    def test_builds_non_actuating_attributable_result(self):
        events = [
            execution("awaiting_owner_approval", "op-1"),
            execution("approved_for_observation", "op-2"),
            execution("collecting_evidence", "op-3"),
            observation(),
            execution("completed", "op-4"),
        ]
        result = build_portal_result({
            "candidate_id": "PTL-EXP-ABC123",
            "node_ids": ["PTL-A"],
        }, events, updated_at="2026-08-28T03:10:00Z")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["conclusion"], "evidence_collected")
        self.assertEqual(result["evidence_summary"]["observation_count"], 1)
        self.assertTrue(result["evidence_summary"]["provenance_complete"])
        self.assertFalse(result["safety"]["actuation_authorized"])
        self.assertFalse(result["safety"]["scientific_support_claimed"])

    def test_rejects_observation_before_approval(self):
        with self.assertRaisesRegex(ValueError, "owner-approved"):
            build_portal_result(
                {"candidate_id": "PTL-EXP-ABC123", "node_ids": []},
                [execution("awaiting_owner_approval", "op-1"), observation()],
            )

    def test_rejects_event_type_payload_mismatch(self):
        event = execution("collecting_evidence", "op-3")
        event["event_type"] = "experiment_execution.completed"
        with self.assertRaisesRegex(ValueError, "does not match state"):
            validate_velyqua_event(event)


if __name__ == "__main__":
    unittest.main()
