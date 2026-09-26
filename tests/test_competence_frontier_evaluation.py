from scripts.evaluate_competence_frontier import evaluate
from scripts.verify_competence_frontier import verify

def test_held_out_frontier_and_independent_verifier():
 r=evaluate();assert r['passed'] and r['candidate']['correct']==13
 v=verify();assert v['independent'] and v['passed']
