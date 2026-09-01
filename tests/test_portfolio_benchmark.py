from app.portfolio_benchmark import score_text, summarize


def test_benchmark_terms():
    result = score_text('semantic provenance', ['semantic', 'provenance'])
    assert result['passed'] == 2
    assert result['score'] == 1.0
    assert summarize([result])['mean_score'] == 1.0
