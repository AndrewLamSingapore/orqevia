from app.portfolio_benchmark import load_cases, score_text, summarize


def test_score_and_summary():
    result = score_text('semantic provenance', ['semantic', 'provenance'])
    assert result['passed'] == 2
    assert result['score'] == 1.0
    summary = summarize([result])
    assert summary == {'cases': 1, 'mean_score': 1.0}


def test_portfolio_corpus_is_versioned_and_complete():
    cases = load_cases()
    categories = {case['category'] for case in cases}
    assert {'retrieval', 'grounding', 'reasoning', 'simulation'} <= categories
    assert all(case.get('id') and case.get('intent') and case.get('expected') for case in cases)
