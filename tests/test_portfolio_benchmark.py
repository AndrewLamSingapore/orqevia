import unittest

from app.portfolio_benchmark import load_cases, score_text, summarize


class PortfolioBenchmarkTests(unittest.TestCase):
    def test_score_and_summary(self):
        result = score_text('semantic provenance', ['semantic', 'provenance'])
        self.assertEqual(result['passed'], 2)
        self.assertEqual(result['score'], 1.0)
        self.assertEqual(summarize([result]), {'cases': 1, 'mean_score': 1.0})

    def test_portfolio_corpus_is_versioned_and_complete(self):
        cases = load_cases()
        categories = {case['category'] for case in cases}
        self.assertTrue({'retrieval', 'grounding', 'reasoning', 'simulation'} <= categories)
        self.assertTrue(all(case.get('id') and case.get('intent') and case.get('expected') for case in cases))


if __name__ == '__main__':
    unittest.main()
