from scripts.evaluate_metacognition import evaluate


def test_held_out_candidate_beats_preserved_baseline():
    result = evaluate()
    assert result["passed"]
    assert result["candidate"]["accuracy"] == 1
    assert result["candidate"]["accuracy"] > result["baseline"]["accuracy"]
    assert result["unknown_detection"] and result["contradiction_detection"]
    assert result["candidate"]["peak_memory_bytes"] < 1_000_000
