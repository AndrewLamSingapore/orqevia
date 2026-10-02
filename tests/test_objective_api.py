from tests.test_agent_dispatch_api import AgentDispatchTests
from unittest.mock import patch

from app import objective_api


class ObjectiveTests(AgentDispatchTests):
    def test_live_objective_submission_uses_ready_work_for_independent_dispatch(self):
        with patch.object(objective_api, 'run_ready_work', wraps=objective_api.run_ready_work) as scheduler:
            response=self.client.post('/api/agents/objectives',headers=self.headers,json={
                'objective':'Classify as yes or no.','task_class':'classification',
                'capabilities':['responsibility.a02','responsibility.a18']})
        assert response.status_code==202,response.text
        assert scheduler.call_count==1
        assert scheduler.call_args.kwargs['max_parallel']==2
        assert [item.id for item in scheduler.call_args.args[0]]==['dispatch-0','dispatch-1']
        assert len(response.json()['steps'])==2

    def test_independent_failure_does_not_block_signed_siblings(self):
        response=self.client.post('/api/agents/objectives',headers=self.headers,json={
            'objective':'Classify as yes or no.','task_class':'classification',
            'capabilities':['responsibility.a02','invented','responsibility.a18']})
        assert response.status_code==202,response.text
        body=response.json()
        assert len([step for step in body['steps'] if 'dispatch' in step])==2
        assert len([step for step in body['steps'] if step.get('state')=='blocked'])==1
        loaded=self.client.get('/api/agents/objectives/'+body['id'],headers=self.headers)
        assert loaded.status_code==200
        assert self.client.get('/api/agents/objectives/'+body['id']).status_code==401
