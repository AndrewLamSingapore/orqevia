from app.release_gate import PUBLIC_GATE_FIELDS, ReleaseGateLedger


def test_release_gate_keeps_only_bounded_aggregate_metadata(tmp_path):
    ledger = ReleaseGateLedger(tmp_path / "release-gate.db")
    public = ledger.record(
        trace_id="trace-1",
        evaluation={
            "version": "2.1",
            "score": 0.514321,
            "released": False,
            "blocking_metrics": ["source_coverage", "required_evidence", "invented_metric"],
            "evidence_gaps": ["SECRET EVIDENCE TEXT", "another gap"],
            "unsupported_claims": ["SECRET CLAIM TEXT"],
            "contradictions": [],
            "rationale": "PRIVATE RATIONALE MUST NEVER LEAVE PRIME",
            "parse_error": None,
            "evaluation_compute": {"model": "private-model"},
        },
    )
    assert set(public) == PUBLIC_GATE_FIELDS
    assert public == {
        "decision": "withheld",
        "score": 0.5143,
        "blocking_metrics": ["required_evidence", "source_coverage"],
        "evidence_gap_count": 2,
        "unsupported_claim_count": 1,
        "contradiction_count": 0,
        "evaluator_valid": True,
        "evaluation_version": "2.1",
    }
    serialized = str(public)
    assert "SECRET" not in serialized
    assert "PRIVATE" not in serialized
    assert "private-model" not in serialized


def test_snapshot_enrichment_attaches_gate_only_to_terminal_reasoning(tmp_path):
    ledger = ReleaseGateLedger(tmp_path / "release-gate.db")
    ledger.record(
        trace_id="trace-2",
        evaluation={
            "version": "2.1",
            "score": 0.9,
            "released": True,
            "blocking_metrics": [],
            "evidence_gaps": [],
            "unsupported_claims": [],
            "contradictions": [],
            "parse_error": None,
        },
    )
    snapshot = {
        "ok": True,
        "summary": {"registered_agents": 29},
        "events": [
            {"trace_id": "trace-2", "agent_id": "A17", "stage": "reasoning", "status": "started"},
            {"trace_id": "trace-2", "agent_id": "A17", "stage": "reasoning", "status": "completed"},
        ],
    }
    enriched = ledger.enrich_snapshot(snapshot)
    assert "gate" not in enriched["events"][0]
    assert enriched["events"][1]["gate"]["decision"] == "released"
    assert enriched["summary"]["withheld_executions_today"] == 0
