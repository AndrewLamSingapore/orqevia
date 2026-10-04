import os
from unittest.mock import patch
from tests.test_harness_api import HarnessApiTests
from app.agent_registry import registered_agent_ids
from app import compute_queue_api
from app.agent_dispatch_api import local_model_backends, _baseline_probe_slot
from app.settings import PrimeSettings


class AgentDispatchTests(HarnessApiTests):
    def setUp(self):
        super().setUp()
        os.environ['PRIME_REGISTRY_V1_ENABLED']='1'

    def tearDown(self):
        os.environ.pop('PRIME_REGISTRY_V1_ENABLED',None)
        super().tearDown()

    def test_baseline_probe_is_authenticated_bounded_and_non_certifying(self):
        payload={'agent_id':'a19','capability_id':'responsibility.a19','timeout_seconds':5}
        with patch('app.agent_execution_live.observe_live_baseline',return_value={
            'agent_id':'a19','state':'EXECUTED','certification':'UNVERIFIED'
        }) as observed:
            denied=self.client.post('/api/agents/probe/baseline',json=payload)
            assert denied.status_code==401
            observed.assert_not_called()
            accepted=self.client.post('/api/agents/probe/baseline',headers=self.headers,json=payload)
            assert accepted.status_code==200,accepted.text
            assert accepted.json()['certification']=='UNVERIFIED'
            observed.assert_called_once_with('a19','responsibility.a19',
                                             authorization=self.headers['Authorization'],timeout_seconds=5)
            excessive=self.client.post('/api/agents/probe/baseline',headers=self.headers,
                                       json={**payload,'timeout_seconds':31})
            assert excessive.status_code==422
            os.environ['PRIME_REGISTRY_V1_ENABLED']='0'
            disabled=self.client.post('/api/agents/probe/baseline',headers=self.headers,json=payload)
            assert disabled.status_code==503

    def test_baseline_probe_rejects_concurrent_request(self):
        _baseline_probe_slot.acquire()
        try:
            response=self.client.post('/api/agents/probe/baseline',headers=self.headers,
                                      json={'agent_id':'a19','capability_id':'responsibility.a19'})
            assert response.status_code==429
        finally:
            _baseline_probe_slot.release()

    def test_all_21_advisory_agents_use_direct_observed_shared_queue(self):
        for actor in sorted(registered_agent_ids(include_orchestrator=False)):
            response=self.client.post('/api/agents/dispatch',headers=self.headers,json={
                'capability':'responsibility.'+actor,'objective':'Classify as yes or no.',
                'task_class':'classification'})
            assert response.status_code==202,response.text
            body=response.json()
            assert body['job']['agent']==actor
            job=compute_queue_api.queue.get(body['job']['id'])
            assert job['harness_envelope'] is None
            assert not job['allow_cloud']
            bypass=self.client.post('/api/compute-queue/jobs',headers=self.headers,
                                    json={'agent':actor,'prompt':'bypass'})
            assert bypass.status_code==202
        assert compute_queue_api.queue.policy.global_concurrency==1

    def test_distinct_deep_local_model_is_routable_as_mini_not_flagship(self):
        settings=PrimeSettings(ollama_base_url='http://fixture',fast_model='small:1b',deep_model='deep:4b',
                               embedding_model='embed',multi_specialist_workers=1)
        backends=local_model_backends(settings)
        assert [(item.name,item.model,item.tier.name) for item in backends]==[
            ('ollama-fast','small:1b','NANO'),('ollama-deep','deep:4b','MINI')]
        same=PrimeSettings(ollama_base_url='http://fixture',fast_model='same',deep_model='same',
                           embedding_model='embed',multi_specialist_workers=1)
        assert len(local_model_backends(same))==1

    def test_scope_and_unavailable_tier_fail_only_the_affected_request(self):
        for capability,tier,expected in [('invented','NANO',422),('responsibility.a02','FLAGSHIP',409)]:
            response=self.client.post('/api/agents/dispatch',headers=self.headers,json={
                'capability':capability,'minimum_tier':tier,'objective':'Analyze evidence'})
            assert response.status_code==expected
        valid=self.client.post('/api/agents/dispatch',headers=self.headers,json={
            'capability':'responsibility.a02','objective':'Classify as yes or no.','task_class':'classification'})
        assert valid.status_code==202,valid.text
