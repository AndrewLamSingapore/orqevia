"""Authenticated HTTP backpressure with real tiny SQLite, no worker/inference."""
import os
import json
from unittest.mock import patch

from tests.test_harness_api import HarnessApiTests
from app import compute_queue_api
from app.action_records import ActionRecord, DirectExecutor
from app.job_queue import JobQueue, QueuePolicy, QueueAdmissionFull


class QueueAdmissionApiTests(HarnessApiTests):
    def setUp(self):
        super().setUp()
        self.registry_patch = patch.dict(os.environ, {'PRIME_REGISTRY_V1_ENABLED': '1'})
        self.registry_patch.start()
        compute_queue_api.queue = JobQueue(os.path.join(self.case.name, 'bounded.db'),
            QueuePolicy(pending_job_limit=2, pending_owner_reserve=1))

    def tearDown(self):
        self.registry_patch.stop()
        super().tearDown()

    def fill_background(self):
        return self.client.post('/api/compute-queue/jobs', headers=self.headers,
            json={'agent': 'a20', 'prompt': 'Classify public fixture', 'priority': 'background'})

    def test_direct_queue_denies_without_insertion_and_owner_reserve_remains(self):
        assert self.fill_background().status_code == 202
        denied = self.fill_background()
        assert denied.status_code == 429
        assert denied.json() == {'detail': 'OWNER_PENDING_RESERVE'}
        assert denied.headers['Retry-After'] == '1'
        assert len(compute_queue_api.queue.list()) == 1
        owner = self.client.post('/api/compute-queue/jobs', headers=self.headers,
            json={'agent': 'a20', 'prompt': 'Owner public fixture', 'priority': 'critical'})
        assert owner.status_code == 202
        exhausted = self.client.post('/api/compute-queue/jobs', headers=self.headers,
            json={'agent': 'a20', 'prompt': 'Owner public fixture 2', 'priority': 'critical'})
        assert exhausted.status_code == 429
        assert exhausted.json() == {'detail': 'PENDING_QUEUE_FULL'}
        assert len(compute_queue_api.queue.list()) == 2

    def test_auth_denial_precedes_admission(self):
        with patch.object(compute_queue_api.queue, 'submit') as submit:
            result = self.client.post('/api/compute-queue/jobs', json={'agent': 'a20', 'prompt': 'test'})
        assert result.status_code == 401
        submit.assert_not_called()

    def test_agent_route_returns_bounded_known_backpressure(self):
        assert self.fill_background().status_code == 202
        result = self.client.post('/api/agents/dispatch', headers=self.headers,
            json={'capability': 'responsibility.a20', 'objective': 'Classify yes or no.',
                'task_class': 'classification', 'priority': 'normal'})
        assert result.status_code == 429
        assert result.json() == {'detail': 'OWNER_PENDING_RESERVE'}
        assert result.headers['Retry-After'] == '1'
        assert len(compute_queue_api.queue.list()) == 1

    def test_objective_retains_blocked_step_not_uncertain_dispatch(self):
        assert self.fill_background().status_code == 202
        result = self.client.post('/api/agents/objectives', headers=self.headers,
            json={'objective': 'Classify yes or no.', 'capability': 'responsibility.a20',
                'task_class': 'classification', 'priority': 'normal'})
        assert result.status_code == 202
        steps = result.json()['steps']
        assert len(steps) == 1
        assert steps[0]['state'] == 'blocked'
        # Preserve the existing public error-redaction contract, not raw errors.
        assert steps[0]['reason'] == 'STEP_DISPATCH_FAILED'
        from app import objective_api
        with objective_api.connect() as db:
            stored = db.execute('SELECT steps_json FROM objectives WHERE id=?', (result.json()['id'],)).fetchone()
        assert json.loads(stored[0])[0]['reason'] == 'OWNER_PENDING_RESERVE'
        assert len(compute_queue_api.queue.list()) == 1

    def test_exception_text_does_not_escape_http(self):
        with patch.object(compute_queue_api.queue, 'submit', side_effect=QueueAdmissionFull('private-path-sentinel')):
            result = self.fill_background()
        assert result.status_code == 429
        assert result.json() == {'detail': 'QUEUE_ADMISSION_FULL'}
        assert 'private-path-sentinel' not in result.text

    def test_legacy_authenticated_harness_path_does_not_escape_as_500(self):
        assert self.fill_background().status_code == 202
        result = self.client.post('/api/harness/pilot/dispatch', headers=self.headers,
            json={'actor_id': 'a14', 'prompt': 'Public dataset check', 'priority': 'normal'})
        assert result.status_code == 429
        assert result.json() == {'detail': 'OWNER_PENDING_RESERVE'}
        assert len(compute_queue_api.queue.list()) == 1

    def test_failed_action_evidence_is_not_converted_to_success(self):
        emitted = []
        class Ledger:
            def emit(self, record, phase, **details):
                emitted.append((phase, details))
                return 'RECORDED'
        action = ActionRecord('case-queue-full', 'a20', 'agent.queue.submit', 'queue')
        executor = DirectExecutor(Ledger())
        def operation():
            raise QueueAdmissionFull('PENDING_QUEUE_FULL')
        try:
            executor.execute(action, operation)
        except QueueAdmissionFull:
            pass
        else:
            raise AssertionError('Admission rejection suppressed')
        assert emitted[0][0] == 'started'
        assert emitted[-1][0] == 'completed'
        assert emitted[-1][1]['success'] is False
        assert emitted[-1][1]['error'] == 'QueueAdmissionFull'
