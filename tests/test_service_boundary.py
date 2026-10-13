"""Actual middleware admission/error behavior; no live credentials or acceptance."""
import asyncio
import json

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from app import direct_entry,capability_broker

OWNER='owner-fixture-key-never-production'


def scope(headers):
    return {'type':'http','http_version':'1.1','method':'POST','scheme':'http',
            'path':'/api/capabilities/core/request','raw_path':b'/api/capabilities/core/request',
            'query_string':b'','headers':headers,'client':('127.0.0.1',1234),'server':('localhost',80)}


def test_authentication_and_declared_size_reject_before_reading(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    calls=[]
    async def receive():
        calls.append('read')
        pytest.fail('Rejected request must not consume body')
    async def next_handler(request):
        pytest.fail('Rejected request must not execute')
    for headers,status in (([],401),([(b'authorization',b'Bearer member-fixture')],401),
                           ([(b'authorization',('Bearer '+OWNER).encode()),(b'content-length',b'300001')],413)):
        response=asyncio.run(direct_entry.bounded_service_requests(Request(scope(headers),receive),next_handler))
        assert response.status_code==status
    assert calls==[]


def test_never_completing_authenticated_upload_times_out(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    monkeypatch.setattr(direct_entry,'SERVICE_BODY_SECONDS',.02)
    stopped=[]
    async def receive():
        try:await asyncio.Future()
        finally:stopped.append(True)
    async def next_handler(request):
        pytest.fail('Unfinished upload must not execute')
    headers=[(b'authorization',('Bearer '+OWNER).encode())]
    response=asyncio.run(direct_entry.bounded_service_requests(Request(scope(headers),receive),next_handler))
    assert response.status_code==408 and stopped==[True]


def test_exact_body_survives_bounded_json_validation(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    raw=b'{ "request_id": "scope-proof", "service": "infrastructure.status.read", "parameters": {} }'
    chunks=iter([raw[:12],raw[12:]])
    async def receive():
        chunk=next(chunks)
        return {'type':'http.request','body':chunk,'more_body':len(chunk)==12}
    async def next_handler(request):
        assert await request.body()==raw
        return JSONResponse({'received':True})
    headers=[(b'authorization',('Bearer '+OWNER).encode())]
    response=asyncio.run(direct_entry.bounded_service_requests(Request(scope(headers),receive),next_handler))
    assert response.status_code==200


def test_streamed_size_and_deep_json_fail_before_operation(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    nested='private-value'
    for _ in range(18):nested={'nested':nested}
    for raw,status in ((b'x'*300001,413),(json.dumps(nested).encode(),422)):
        async def receive():return {'type':'http.request','body':raw,'more_body':False}
        async def next_handler(request):pytest.fail('Malformed bounded request must not execute')
        headers=[(b'authorization',('Bearer '+OWNER).encode())]
        response=asyncio.run(direct_entry.bounded_service_requests(Request(scope(headers),receive),next_handler))
        assert response.status_code==status
        assert b'private-value' not in response.body


@pytest.mark.parametrize('error,status',[(PermissionError('PRIVATE_FAILURE'),403),
                                         (ValueError('PRIVATE_FAILURE'),422),
                                         (RuntimeError('PRIVATE_FAILURE'),503),
                                         (capability_broker.ServiceBusy('PRIVATE_FAILURE'),429)])
def test_route_errors_are_sanitized_and_member_cannot_invoke(monkeypatch,error,status):
    monkeypatch.setenv('PRIME_SPINE_TOKEN',OWNER)
    calls=[]
    def execute(body):
        calls.append(body.request_id)
        raise error
    monkeypatch.setattr(capability_broker,'execute_core_request',execute)
    body={'request_id':'scope-proof','service':'infrastructure.status.read','parameters':{}}
    with TestClient(direct_entry.app,raise_server_exceptions=False) as client:
        denied=client.post('/api/capabilities/core/request',json=body,headers={'Authorization':'Bearer member-fixture'})
        assert denied.status_code==401 and calls==[]
        result=client.post('/api/capabilities/core/request',json=body,headers={'Authorization':'Bearer '+OWNER})
        assert result.status_code==status and calls==['scope-proof']
        assert 'PRIVATE_FAILURE' not in result.text
