from app.portfolio_benchmark import score_text, summarize

def test_score_and_summary():
    result=score_text('semantic provenance',['semantic','provenance'])
    assert result['score']==1.0
    assert summarize([result])['mean_score']==1.0
