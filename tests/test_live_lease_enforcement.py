import json
from unittest import mock
import pytest
from tests.test_harness_api import HarnessApiTests
from app import compute_queue_api,harness_api


class LiveLeaseTests(HarnessApiTests):
    def dispatch_job(self):
        r=self.client.post('/api/harness/pilot/dispatch',headers=self.headers,
                           json={'actor_id':'a14','prompt':'lease enforcement test','max_retries':2})
        assert r.status_code==202,r.text
        b=r.json()
        return compute_queue_api.queue.get(b['job']['id']),b['harness']['lease_id']

    def test_revoked_queued_job_never_reaches_model(self):
        job,lease=self.dispatch_job()
        r=self.client.post('/api/harness/leases/'+lease+'/revoke',headers=self.headers,json={'reason':'owner stop'})
        assert r.status_code==200
        with mock.patch.object(compute_queue_api.httpx,'Client') as transport:
            with pytest.raises(PermissionError,match='lease revoked'):
                compute_queue_api._execute(job,compute_queue_api.providers()[0])
            transport.assert_not_called()

    def test_lease_checked_again_during_stream(self):
        job,lease=self.dispatch_job();harness,_=harness_api._runtime()
        def lines():
            yield json.dumps({'message':{'content':'first'}})
            harness.revoke(lease,reason='revoke while generating',revoked_by='owner')
            yield json.dumps({'message':{'content':'must be discarded'},'done':True})
        response=mock.MagicMock();response.iter_lines.side_effect=lines
        client=mock.MagicMock();client.__enter__.return_value.stream.return_value.__enter__.return_value=response
        with mock.patch.object(compute_queue_api.httpx,'Client',return_value=client):
            with pytest.raises(PermissionError,match='lease revoked'):
                compute_queue_api._execute(job,compute_queue_api.providers()[0])
        assert client.__enter__.return_value.stream.return_value.__exit__.called

    def test_missing_or_modified_binding_fails_closed(self):
        job,_=self.dispatch_job()
        with pytest.raises(PermissionError,match='signed lease'):
            compute_queue_api._validate_job_lease({**job,'harness_envelope':None})
        with pytest.raises(PermissionError,match='does not match'):
            compute_queue_api._validate_job_lease({**job,'prompt':'changed'})
        with pytest.raises(PermissionError,match='parameters changed'):
            compute_queue_api._validate_job_lease({**job,'ram_mb':9999})

    def test_active_lease_checks_do_not_consume_again(self):
        job,_=self.dispatch_job()
        compute_queue_api._validate_job_lease(job)
        compute_queue_api._validate_job_lease(job)
        harness,_=harness_api._runtime()
        with harness.connect() as db:assert db.execute('select count(*) from harness_executions').fetchone()[0]==1

    def test_revocation_requires_owner_authentication(self):
        _,lease=self.dispatch_job()
        assert self.client.post('/api/harness/leases/'+lease+'/revoke',json={'reason':'stop'}).status_code==401

    def test_authority_denial_is_not_retried(self):
        job,_=self.dispatch_job();q=compute_queue_api.queue
        assert q.claim('test-worker',compute_queue_api.providers())['id']==job['id']
        assert q.finish(job['id'],error='PermissionError: lease revoked',retryable=False)['status']=='failed'

    def test_streaming_deadline_bounds_total_execution(self):
        b=self.client.post('/api/harness/pilot/dispatch',headers=self.headers,
                           json={'actor_id':'a14','prompt':'bounded deadline','timeout_seconds':1}).json()
        job=compute_queue_api.queue.get(b['job']['id'])
        response=mock.MagicMock();response.iter_lines.return_value=iter([json.dumps({'message':{'content':'late'},'done':True})])
        client=mock.MagicMock();client.__enter__.return_value.stream.return_value.__enter__.return_value=response
        with mock.patch.object(compute_queue_api.httpx,'Client',return_value=client),mock.patch.object(compute_queue_api.time,'monotonic',side_effect=[0,2]):
            with pytest.raises(TimeoutError,match='deadline'):
                compute_queue_api._execute(job,compute_queue_api.providers()[0])
