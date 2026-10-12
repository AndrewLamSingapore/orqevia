"""Reproducible 21-identity simulator evaluation with separate-process restart.

All authorization receipts here are synthetic fixtures. No live inference,
DigitalOcean deployment, Azure signing or agent certification is performed.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_registry import agent_record, registered_agent_ids, REGISTRY_PATH
from app.experiential_exploration import ExplorationSandbox, HELD_OUT, simulate
from app.phase2_intelligence import digest


def verifier(receipt, binding):
    return receipt.get('fixture_authorization') == binding


def reviewer(agent):
    record = agent_record(agent)
    return record['reports_to'] if not record['can_delegate'] else next(
        a for a in sorted(registered_agent_ids(include_orchestrator=False))
        if a != agent and agent_record(a)['can_delegate'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--phase', choices=['all', 'learn', 'restart'], default='all')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.phase == 'all':
        for phase in ('learn', 'restart'):
            subprocess.run([sys.executable, __file__, '--output', str(args.output),
                            '--phase', phase], check=True, timeout=120)
        return
    start = time.monotonic()
    sandbox = ExplorationSandbox(args.output/'sandbox', promotion_verifier=verifier)
    ids = sorted(registered_agent_ids(include_orchestrator=False))
    assert len(ids) == 21
    if args.phase == 'learn':
        rows = []
        for agent in ids:
            candidate = sandbox.explore(sandbox.start(agent))
            challenge = sandbox.challenge(candidate['candidate_id'], reviewer(agent))
            assert challenge['disposition'] == 'STORE'
            authorization = {'fixture_authorization': sandbox.admission_binding(candidate['candidate_id'])}
            version = sandbox.admit(candidate['candidate_id'], authorization=authorization)
            rows.append({'agent_id': agent, 'candidate_id': candidate['candidate_id'],
                         'reviewer': reviewer(agent), 'version': version})
        (args.output/'learn.json').write_text(json.dumps({
            'pid': __import__('os').getpid(), 'rows': rows,
            'seconds': time.monotonic()-start}, indent=2), encoding='utf-8')
        print('PASS: 21 canonical identities completed bounded symbolic exploration; local fixture admission only.')
    else:
        learned = json.loads((args.output/'learn.json').read_text())
        assert learned['pid'] != __import__('os').getpid(), 'evaluation must restart in a different process'
        matrix = []
        for item in learned['rows']:
            agent = item['agent_id']; record = agent_record(agent)
            candidate = sandbox.candidate(item['candidate_id'])
            baseline = [simulate('preserve', task)['ordered'] for task in HELD_OUT]
            post = [sandbox.transfer(agent, item['reviewer'], task)['ordered'] for task in HELD_OUT]
            assert all(post) and sum(post) > sum(baseline)
            assert len(sandbox.history(agent)) == 9
            matrix.append({
                'agent_id': agent, 'name': record['name'], 'role': record['role'],
                'capability_requirements': record['capability_requirements'],
                'tool_eligibility': record['tool_eligibility'], 'model': record['model'],
                'source_simulator': 'PASS', 'separate_process_retention': 'PASS',
                'local_validated_transfer': 'PASS', 'trial_budget': 12, 'trials_consumed': 9,
                'baseline_heldout_pass': sum(baseline), 'post_heldout_pass': sum(post),
                'heldout_cases': len(HELD_OUT), 'candidate_id': item['candidate_id'],
                'training_failures_retained': candidate['failed_strategies'],
                'execution_adapter': 'AgentAuthorityRuntime consultation + local finite simulator',
                'live_model_self_direction': 'NOT VERIFIED', 'role_specific_transfer': 'NOT VERIFIED',
                'individual_capability_evidence': {
                    'autonomous_exploration_without_rewards': {'fixture': 'PASS', 'live_model': 'NOT VERIFIED'},
                    'self_generated_experiment_design': {'fixture': 'finite predeclared strategy search', 'live_model': 'NOT VERIFIED'},
                    'repeated_experimentation_and_adaptation': {'fixture': 'PASS', 'live_model': 'NOT VERIFIED'},
                    'durable_retention_after_restart': {'fixture': 'PASS', 'live_model': 'NOT VERIFIED'},
                    'reuse_previous_skills': {'fixture': 'PASS', 'live_model': 'NOT VERIFIED'},
                    'held_out_transfer': {'fixture': 'PASS', 'role_specific': 'NOT VERIFIED'},
                    'independent_improvement_verification': {'fixture': 'different registered reviewer identity; deterministic oracle', 'independent_model': 'NOT VERIFIED'},
                    'failed_experiment_recovery': {'fixture': 'counterexamples retained; source recovery tests PASS', 'live_model': 'NOT VERIFIED'},
                    'validated_knowledge_transfer': {'fixture': 'PASS via canonical consultation graph', 'live_model': 'NOT VERIFIED'},
                    'security_authority_compliance': {'fixture': 'default deny + bounded local simulator', 'production': 'NOT VERIFIED'}},
                'production_promotion': 'NOT VERIFIED', 'azure_l7': 'NOT VERIFIED',
                'weight_training': False, 'production_grants': False})
        result = {'scope': 'LOCAL_SYMBOLIC_FIXTURE_ONLY', 'source_agents': 21,
                  'live_model_certified': 0, 'registry_sha256': __import__('hashlib').sha256(REGISTRY_PATH.read_bytes()).hexdigest(),
                  'heldout_hash': digest(HELD_OUT), 'restart_pid': __import__('os').getpid(),
                  'learning_pid': learned['pid'], 'seconds': time.monotonic()-start,
                  'agents': matrix}
        (args.output/'21-agent-matrix.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('PASS: 21 separate-process retention/held-out/transfer fixture evaluations; live model and Azure L7 remain unverified.')


if __name__ == '__main__':
    main()
