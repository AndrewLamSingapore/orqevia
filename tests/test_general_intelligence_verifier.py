from scripts.verify_general_intelligence_candidate import verify


def test_independent_general_intelligence_verifier():
    result=verify()
    assert result["independent"] and result["passed"]
    assert len(result["checks"])==7 and all(result["checks"].values())
