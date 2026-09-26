from scripts.evaluate_general_intelligence import evaluate


def test_cross_domain_held_out_candidate_beats_baseline():
    result=evaluate()
    assert result["passed"]
    assert result["candidate"]["accuracy"]==1
    assert result["candidate"]["accuracy"]>result["baseline"]["accuracy"]
    assert len(result["domains"])>=10
    assert result["candidate"]["peak_memory_bytes"]<1_000_000
