from app.compute_ledger import ComputeLedger


def test_summary_and_scorecard_rank_measured_routes(tmp_path):
    ledger = ComputeLedger(str(tmp_path / "compute.db"))
    ledger.record(task_id="a", stage="answer", provider="ollama", model="gemma3:1b", latency_ms=1000, success=True, output_units=30, metadata={"output_tokens_per_second": 30.0})
    ledger.record(task_id="b", stage="answer", provider="ollama", model="gemma3:1b", latency_ms=1200, success=True, output_units=28, metadata={"output_tokens_per_second": 28.0})
    ledger.record(task_id="c", stage="verify", provider="ollama", model="slow", latency_ms=3000, success=False, metadata={"output_tokens_per_second": 5.0})

    summary = ledger.summary()
    fast = next(group for group in summary["groups"] if group["model"] == "gemma3:1b")
    assert fast["calls"] == 2
    assert fast["failed_calls"] == 0
    assert fast["p95_latency_ms"] == 1200.0
    assert fast["stages"] == ["answer"]

    scorecard = ledger.scorecard()
    assert scorecard["selection_mode"] == "evidence_only"
    assert scorecard["ranking"][0]["model"] == "gemma3:1b"
    assert scorecard["ranking"][-1]["failed_calls"] == 1
