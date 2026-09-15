from tests.test_agent_dispatch_api import AgentDispatchTests


class EngineeringTests(AgentDispatchTests):
    def test_builder_and_tester_execute_real_sandbox_and_imports_fail_closed(self):
        body={'source':'(module (func (export "value") (result i32) i32.const 42))','export':'value'}
        for role in ['A12 Builder','A13 Test Engineer']:
            response=self.client.post('/api/agents/engineering/wasm',headers=self.headers,json={**body,'role':role})
            assert response.status_code==200,response.text
            assert response.json()['result']['result']==42
        assert self.client.post('/api/agents/engineering/wasm',json={**body,'role':'A12 Builder'}).status_code==401
        response=self.client.post('/api/agents/engineering/wasm',headers=self.headers,json={**body,
            'role':'A12 Builder','source':'(module (import "host" "filesystem" (func)))'})
        assert response.status_code==403
