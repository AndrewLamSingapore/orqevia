"""Deterministic product/security checks in isolated data directories only."""
import os,sys,uuid
from pathlib import Path
from validate_canonical import ROOT,validate

def main():
    validate()
    data=Path(os.environ['PRIME_DATA_DIR']).resolve()
    data.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('PRIME_COMPUTE_QUEUE_DB',str(data/'queue.db'))
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(ROOT))
    import pytest
    class Fixtures:
        @pytest.fixture
        def tmp_path(self):
            path=data/('test-'+uuid.uuid4().hex);path.mkdir();return path
    names=['status_authority','canonical_state','operational_manifest','registry_v1','dell_node_sync','truth_reconciler','agent_registry','task_continuation','interface_contract','pwa_sessions',
           'product_handoff','operational_workflows','workflow_objective_integration',
           'cloud_capacity_recovery','huggingface_provider','hf_file_secret','production_compatibility','public_task_errors',
           'interface_server','consequential_intent','stable_spine','sink_guard',
           'provider_failure_boundaries','interface_cloud_policy',
           'direct_execution','connector_sdk']
    names.append('supreme_intelligence_benchmark')
    names.append('supreme_independence_candidate')
    names.append('independence_dependency_matrix')
    names.append('capability_router')
    names.append('model_capability_verifier')
    names.append('governed_knowledge')
    names.append('governed_knowledge_durability')
    names.append('memory_durability_verifier')
    names.append('structured_output')
    names.append('structured_output_verifier')
    names.append('semantic_evidence_adversarial')
    names.append('authoritative_result_metadata')
    names.append('supreme_integration')
    names.append('supreme_integration_verifier')
    names.append('candidate_manifest')
    names.append('independence_phase_verifier')
    names.append('vision_evidence')
    names.append('vision_adversarial')
    names.append('vision_candidate_verifier')
    names.append('jarvis_response_contract')
    names.append('jarvis_candidate_verifier')
    names.append('application_boundaries')
    names.append('capability_register')
    names.append('cross_domain_security_closure')
    names.append('engineering_verification_gate')
    names.append('candidate_provenance')
    names.append('aef_controls_verifier')
    names.append('metacognition')
    names.append('metacognitive_evaluation')
    names.append('general_intelligence')
    names.append('general_intelligence_evaluation')
    names.append('general_intelligence_verifier')
    names.append('competence_frontier')
    names.append('competence_frontier_evaluation')
    names.append('portfolio_reconciliation')
    names.append('evidence_lens_qualification_receipt')
    names.append('lens_claim_authority_current')
    names.append('evidence_lens_live_slice')
    names.append('job_queue')
    names.append('agent_role_contract_matrix')
    names.append('agent_certification')
    names.append('agent_certification_manifest_json')
    names.append('agent_capability_route')
    names.append('agent_cert_attestation')
    names.append('agent_cert_ed25519')
    names.append('agent_cert_signer')
    names.append('agent_cert_azure_es256')
    names.append('agent_cert_azure_signer')
    names.append('azure_verifier_live_canary')
    names.append('azure_verifier_observation_canary')
    names.append('agent_cert_plan')
    names.append('agent_execution_probe')
    names.append('agent_execution_live')
    names.append('agent_dispatch_api')
    names.append('agent_cert_cases')
    names.append('agent_capability_observatory')
    names.append('agent_cert_numeric')
    names.append('agent_cert_numeric_boundaries')
    names.append('agent_cert_rates')
    names.append('agent_cert_weighted')
    names.append('agent_cert_data_quality')
    names.append('agent_cert_portfolio')
    names.append('agent_cert_cost')
    names.append('agent_cert_a28_risk')
    names.append('agent_cert_a29_release')
    names.append('agent_cert_role_g1')
    names.append('agent_cert_role_group_two')
    names.append('multi_invocation')
    names.append('ssd_thermal')
    names.append('rollback_delta')
    names.append('agent_cert_boundary')
    names.append('agent_cert_a17_boundary')
    names.append('agent_cert_execution')
    names.extend(['agent_artifact_runtime_binding', 'agent_cert_deterministic_observation',
                  'agent_cert_transport', 'agent_cert_cloud_observation',
                  'agent_cert_review_tool', 'agent_cert_review_dispatch',
                  'agent_cert_reviewed_signing', 'sign_admitted_agent_cases',
                  'collect_agent_cert_case', 'agent_cert_success_error_contract'])
    names.append('a19_reviewed_case_admission_20261007')
    names.extend(['agent_cert_identity_review', 'agent_cert_identity_dispatch',
                  'agent_cert_identity_signing'])
    names.extend(['agent_cert_initialization', 'agent_cert_initialization_review',
                  'agent_cert_initialization_dispatch', 'agent_cert_initialization_signing',
                  'agent_cert_initialization_fleet', 'agent_cert_initialization_fleet_events',
                  'agent_cert_secondary_roles', 'agent_cert_secondary_execution',
                  'agent_cert_secondary_integration', 'agent_cert_secondary_transport'])
    names.extend(['agent_cert_readiness', 'objective_domain_provenance'])
    names.append('collect_agent_cert_event')
    names.extend(['agent_cert_event_api', 'agent_cert_operator_io',
                  'agent_cert_a19_general', 'agent_cert_a19_general_integration'])
    names.extend(['agent_cert_a19_baseline', 'agent_cert_a19_baseline_integration',
                  'agent_cert_artifact_events'])
    names.extend(['agent_cert_artifact_paths', 'agent_cert_artifact_signing',
                  'agent_cert_artifact_admission', 'agent_cert_operator_artifact'])
    names.extend(['agent_cert_authority_events', 'agent_cert_authority_chain'])
    names.append('agent_cert_hf_case_provider')
    names.append('backend_fault_diagnostics')
    names.append('mlp_fabric')
    names.append('hf_admission')
    names.append('hf_prompt_scope')
    names.append('agent_cert_a19_cases')
    names.extend(['agent_cert_a19_format_contract', 'agent_cert_role_review',
                  'agent_cert_review_tool_cases', 'agent_cert_transport_cases',
                  'agent_cert_case_bridge', 'agent_cert_case_bridge_independent',
                  'agent_cert_dispatch_cases'])
    names.append('provider_rejection_ambiguity')
    names.extend(['hf_fallback','provider_circuit','provider_circuit_integration','hf_serverless','objective_inference_evidence'])
    names.append('hf_observation_api')
    names.append('hf_qa_execution')
    names.append('system_architecture')
    names.extend(['response_schema', 'role_structured_execution',
                  'agent_cert_structured_roles'])
    paths=[ROOT/'tests'/('test_'+name+'.py') for name in names]
    # Missing suites must fail visibly rather than silently reducing coverage.
    missing=[str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing:raise RuntimeError({'missing_test_suites':missing})
    return pytest.main(['-p','no:cacheprovider','-p','no:tmpdir','-q',
                       '--junitxml',str(data/'canonical-ci.xml'),*[str(p) for p in paths]],plugins=[Fixtures()])
if __name__=='__main__':raise SystemExit(main())
