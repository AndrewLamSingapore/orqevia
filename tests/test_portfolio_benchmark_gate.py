from app.portfolio_benchmark import score_text

def test_score_text():
    assert score_text('semantic provenance',['semantic','provenance'])['score']==1.0
