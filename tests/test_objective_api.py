from tests.test_agent_dispatch_api import AgentDispatchTests


class ObjectiveTests(AgentDispatchTests):
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
