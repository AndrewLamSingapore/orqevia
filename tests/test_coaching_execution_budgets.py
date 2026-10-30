"""Task-specific producer budgets without inference, production DBs or retries."""
import os
from unittest.mock import patch

import pytest

from app.agent_coaching import CoachingController, coaching_execution_seconds
from app.job_queue import JobQueue


def test_role_and_probability_have_distinct_patient_active_budgets():
    with patch.dict(os.environ, {}, clear=True):
        assert coaching_execution_seconds('role') == 600
        assert coaching_execution_seconds('probability-foundations') == 1800


def test_explicit_global_setting_and_program_override_are_honored():
    with patch.dict(os.environ, {
        'ORQEVIA_COACHING_EXECUTION_SECONDS': '1200',
        'ORQEVIA_COACHING_ROLE_EXECUTION_SECONDS': '900',
    }, clear=True):
        assert coaching_execution_seconds('role') == 900
        assert coaching_execution_seconds('probability-foundations') == 1200


@pytest.mark.parametrize('value,expected', [('NaN', 1800), ('invalid', 1800), ('0', 60), ('999999', 7200)])
def test_malformed_and_excessive_probability_settings_remain_safe(value, expected):
    with patch.dict(os.environ, {'ORQEVIA_COACHING_PROBABILITY_EXECUTION_SECONDS': value}, clear=True):
        assert coaching_execution_seconds('probability-foundations') == expected


def test_unknown_program_is_rejected():
    with pytest.raises(ValueError, match='unknown coaching program'):
        coaching_execution_seconds('unregistered')


@pytest.mark.parametrize('program,expected', [('role', 600), ('probability-foundations', 1800)])
def test_actual_controller_submission_uses_task_budget_and_preserves_waiting_job(tmp_path, program, expected):
    with patch.dict(os.environ, {}, clear=True):
        queue = JobQueue(tmp_path/'queue.db')
        controller = CoachingController(tmp_path/'coaching.db',queue,
                                        source_revision='a'*40, model='fixture-local')
        controller.ensure_cohort(program)
        assert controller.tick() == 'SUBMITTED'
        job = queue.list()[0]
        assert job['timeout_seconds'] == expected
        assert job['allow_cloud'] == 0 and job['max_cost_usd'] == 0 and job['max_retries'] == 0
        restarted = CoachingController(tmp_path/'coaching.db',queue,
                                       source_revision='a'*40, model='fixture-local')
        assert restarted.tick() == 'WAITING'
        assert len(queue.list()) == 1
        assert queue.get(job['id'])['timeout_seconds'] == expected
