import os
from tests.test_harness_api import HarnessApiTests
from app.agent_registry import registered_agent_ids
from app import compute_queue_api


class AgentDispatchTests(HarnessApiTests):
    def setUp(self):
        super().setUp()
        os.environ['PRIME_REGISTRY_V1_ENABLED']='1'

    def tearDown(self):
        os.environ.pop('PRIME_REGISTRY_V1_ENABLED',None)
        super().tearDown()

    def test_all_21_advisory_agents_use_signed_shared_queue(self):
        for actor in sorted(registered_agent_ids(include_orchestrator=False)):
            response=self.client.post('/api/agents/dispatch',headers=self.headers,json={
                'capability':'responsibility.'+actor,'objective':'Summarize the supplied evidence.'})
            assert response.status_code==202,response.text
            body=response.json()
            assert body['job']['agent']==actor
            job=compute_queue_api.queue.get(body['job']['id'])
            compute_queue_api._validate_job_lease(job)
            assert not job['allow_cloud']
            bypass=self.client.post('/api/compute-queue/jobs',headers=self.headers,
                                    json={'agent':actor,'prompt':'bypass'})
            assert bypass.status_code==409
        assert compute_queue_api.queue.policy.global_concurrency==1

    def test_scope_and_unavailable_tier_fail_only_the_affected_request(self):
        for capability,tier,expected in [('invented','NANO',422),('responsibility.a02','FLAGSHIP',409)]:
            response=self.client.post('/api/agents/dispatch',headers=self.headers,json={
                'capability':capability,'minimum_tier':tier,'objective':'Analyze evidence'})
            assert response.status_code==expected
        valid=self.client.post('/api/agents/dispatch',headers=self.headers,json={
            'capability':'responsibility.a02','objective':'Plan the evidence review'})
        assert valid.status_code==202,valid.text
