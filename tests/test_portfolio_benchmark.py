from app.portfolio_benchmark import score_text

def test_benchmark_terms():
    assert score_text('semantic provenance',['semantic','provenance'])['passed']==2
