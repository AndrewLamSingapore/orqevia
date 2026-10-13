"""Verify recorded bridge routes under the real authenticated bounded composition."""
from fastapi.testclient import TestClient
from app import direct_entry, agent_tool_bridge_api
OWNER='isolated-owner-token-at-least-32-bytes'

def test_empty_control_and_required_creation_under_real_boundary(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    calls=[]
    class Probe:
        def stop(self,job):calls.append(job);return {'state':'STOPPED'}
    monkeypatch.setattr(agent_tool_bridge_api,'bridge',lambda:Probe())
    with TestClient(direct_entry.app,raise_server_exceptions=False) as client:
        path='/api/agent-tool-bridge/sessions/00000000-0000-0000-0000-000000000001/stop'
        assert client.post(path).status_code==401
        assert client.post(path,headers={'Authorization':'Bearer member'}).status_code==401
        assert calls==[]
        response=client.post(path,headers={'Authorization':'Bearer '+OWNER})
        assert response.status_code==200 and response.json()['state']=='STOPPED'
        assert len(calls)==1
        assert client.post('/api/agent-tool-bridge/sessions',headers={'Authorization':'Bearer '+OWNER}).status_code==422
