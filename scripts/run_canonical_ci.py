"""Deterministic product/security checks in isolated data directories only."""
import os,sys,uuid
from pathlib import Path
from validate_ssot import ROOT,validate

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
    names=['canonical_state','operational_manifest','registry_v1','dell_node_sync','truth_reconciler','agent_registry','task_continuation','interface_contract','pwa_sessions',
           'product_handoff','operational_workflows','workflow_objective_integration',
           'cloud_capacity_recovery','production_compatibility','public_task_errors',
           'interface_server','consequential_intent','stable_spine','sink_guard',
           'provider_failure_boundaries','interface_cloud_policy',
           'direct_execution','connector_sdk']
    names.append('supreme_intelligence_benchmark')
    names.append('supreme_independence_candidate')
    names.append('capability_router')
    names.append('model_capability_verifier')
    names.append('governed_knowledge')
    names.append('structured_output')
    names.append('structured_output_verifier')
    names.append('supreme_integration')
    names.append('supreme_integration_verifier')
    paths=[ROOT/'tests'/('test_'+name+'.py') for name in names]
    # Missing suites must fail visibly rather than silently reducing coverage.
    missing=[str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    if missing:raise RuntimeError({'missing_test_suites':missing})
    return pytest.main(['-p','no:cacheprovider','-p','no:tmpdir','-q',
                       '--junitxml',str(data/'canonical-ci.xml'),*[str(p) for p in paths]],plugins=[Fixtures()])
if __name__=='__main__':raise SystemExit(main())
