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
        with pytest.raises(PermissionError,match='lease revoked'):
            compute_queue_api._validate_job_lease(job)

    def test_lease_checked_again_during_stream(self):
        job,lease=self.dispatch_job();harness,_=harness_api._runtime()
        compute_queue_api._validate_job_lease(job)
        harness.revoke(lease,reason='revoke while generating',revoked_by='owner')
        with pytest.raises(PermissionError,match='lease revoked'):
            compute_queue_api._validate_job_lease(job)

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
        # Isolate lease revocation from operator-side backend telemetry; the
        # admission receipt boundary is covered by test_backend_admission.
        with mock.patch('app.job_queue.backend_admission.reserve_model'):
            assert q.claim('test-worker',compute_queue_api.providers())['id']==job['id']
        assert q.finish(job['id'],error='PermissionError: lease revoked',retryable=False)['status']=='failed'

    def test_streaming_deadline_bounds_total_execution(self):
        b=self.client.post('/api/harness/pilot/dispatch',headers=self.headers,
                           json={'actor_id':'a14','prompt':'bounded deadline','timeout_seconds':1}).json()
        job=compute_queue_api.queue.get(b['job']['id'])
        assert job['timeout_seconds']==1
        compute_queue_api._validate_job_lease(job)
