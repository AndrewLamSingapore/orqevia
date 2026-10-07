from tests.test_agent_dispatch_api import AgentDispatchTests
from types import SimpleNamespace
from unittest.mock import patch

from app import compute_profile


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
        assert response.status_code==422
        assert response.json()['detail']['state']=='GUEST_FAILED'

    def test_bounded_wasm_does_not_require_a_measured_model_but_honors_ram_reserve(self):
        import psutil
        body={'role':'A12 Builder','source':'(module (func (export "value") (result i32) i32.const 42))',
              'export':'value'}
        with patch.object(compute_profile,'runtime_compute_profile',return_value={
                'minimum_available_mib':128,'models':{}}):
            with patch.object(psutil,'virtual_memory',return_value=SimpleNamespace(available=129*1048576)):
                response=self.client.post('/api/agents/engineering/wasm',headers=self.headers,json=body)
                assert response.status_code==200,response.text
                assert response.json()['result']['result']==42
            with patch.object(psutil,'virtual_memory',return_value=SimpleNamespace(available=127*1048576)):
                response=self.client.post('/api/agents/engineering/wasm',headers=self.headers,json=body)
                assert response.status_code==503,response.text
                assert response.json()['detail']=='Bounded engineering memory reserve reached'
