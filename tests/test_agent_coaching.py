"""Isolated controller/assessor tests; no model, cloud or certification claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.agent_coaching import CoachingController, effective_prompt, request_for
from app.coaching_exercises import METHODS, _case, practice_request, review_practice
from app.job_queue import JobQueue


class CoachingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = lambda: 2000000.0
        self.queue = JobQueue(self.root/'queue.db')
        self.controller = CoachingController(self.root/'coaching.db',self.queue,
            source_revision='a'*40,model='fixture-local',clock=self.clock)

    def tearDown(self):
        self.temp.cleanup()

    def complete(self, response='{}'):
        with self.queue.connect() as db:
            db.execute("UPDATE compute_jobs SET status='completed',result=?,started_at='2026-01-01T00:00:00Z',completed_at='2026-01-01T00:01:00Z' WHERE status='queued'",(response,))

    def test_every_registered_role_has_disjoint_practice_and_discriminating_assessor(self):
        from app.agent_registry import registered_agent_ids
        self.assertEqual(set(METHODS),registered_agent_ids(include_orchestrator=False))
        for agent in METHODS:
            for seed in [1001,1002,1014]:
                with self.subTest(agent=agent,seed=seed):
                    request = practice_request(agent,seed)
                    _,expected = _case(agent,seed)
                    self.assertTrue(review_practice(agent,seed,json.dumps(expected))[0])
                    self.assertFalse(review_practice(agent,seed,'{}')[0])
                    self.assertNotIn('expected',json.dumps(request))
                    self.assertNotEqual(request['context'],request_for(agent,'baseline',seed).get('context'))
                    for key,value in expected.items():
                        forged = dict(expected);forged[key] = 'incorrect' if type(value) is not str else False
                        self.assertFalse(review_practice(agent,seed,json.dumps(forged))[0],key)

    def test_grader_rejects_duplicate_keys_nonfinite_and_bool_integer_confusion(self):
        _,expected = _case('a06',1001)
        self.assertFalse(review_practice('a06',1001,'{"x":1,"x":2}')[0])
        self.assertFalse(review_practice('a06',1001,'{"x":NaN}')[0])
        expected['causal_effect_proven'] = 0
        self.assertFalse(review_practice('a06',1001,json.dumps(expected))[0])

    def test_exact_original_acceptance_request_is_retained(self):
        for agent in METHODS:
            before,before_prompt = effective_prompt(agent,'baseline',1001)
            after,after_prompt = effective_prompt(agent,'acceptance',1001)
            self.assertEqual(before,after)
            self.assertNotEqual(before_prompt,after_prompt)
            self.assertIn(METHODS[agent],after_prompt)

    def test_cohort_is_unique_and_has_21_logical_sessions(self):
        self.assertIsNotNone(self.controller.ensure_cohort())
        self.assertIsNone(self.controller.ensure_cohort())
        with self.controller.connect() as db:
            self.assertEqual(db.execute('select count(*) from coaching_sessions').fetchone()[0],21)

    def test_only_one_shared_queue_job_and_restart_continues_it(self):
        self.controller.ensure_cohort()
        self.assertEqual(self.controller.tick(),'SUBMITTED')
        restarted = CoachingController(self.root/'coaching.db',self.queue,source_revision='a'*40,model='fixture-local',clock=self.clock)
        self.assertEqual(restarted.tick(),'WAITING')
        self.assertEqual(len(self.queue.list()),1)
        self.complete()
        self.assertEqual(restarted.tick(),'FAIL')
        self.assertEqual(restarted.tick(),'SUBMITTED')

    def test_uncertain_submission_does_not_duplicate_existing_queue_job(self):
        self.controller.ensure_cohort()
        original = self.queue.submit
        crashed = [False]
        def uncertain(**args):
            result = original(**args)
            if not crashed[0]:
                crashed[0] = True
                raise RuntimeError('fixture process crash after queue commit')
            return result
        with patch.object(self.queue,'submit',side_effect=uncertain):
            with self.assertRaises(RuntimeError):self.controller.tick()
            self.assertEqual(self.controller.tick(),'SUBMITTED')
        self.assertEqual(len(self.queue.list()),1)

    def test_owner_work_precedes_coaching(self):
        self.controller.ensure_cohort()
        self.queue.submit(agent='a02',prompt='fixture Owner work',priority='critical')
        self.assertEqual(self.controller.tick(),'OWNER_QUEUE_BUSY')
        self.assertEqual(len(self.queue.list()),1)

    def test_source_change_blocks_resume_instead_of_relabelling_old_work(self):
        self.controller.ensure_cohort()
        newer = CoachingController(self.root/'coaching.db',self.queue,source_revision='b'*40,model='fixture-local',clock=self.clock)
        self.assertEqual(newer.tick(),'SOURCE_CHANGED')
        self.assertEqual(len(self.queue.list()),0)

    def test_practice_retries_are_bounded_and_original_failures_remain(self):
        self.controller.ensure_cohort()
        with self.controller.connect() as db:
            db.execute("UPDATE coaching_sessions SET state='DONE' WHERE agent!='a06'")
        for expected_phase in ['baseline','practice','practice','acceptance']:
            self.assertEqual(self.controller.tick(),'SUBMITTED')
            with self.controller.connect() as db:
                row=db.execute("SELECT * FROM coaching_sessions WHERE agent='a06'").fetchone()
                self.assertEqual(row['phase'],expected_phase)
            self.complete()
            self.assertEqual(self.controller.tick(),'FAIL')
        self.assertEqual(self.controller.tick(),'IDLE')
        with self.controller.connect() as db:
            self.assertEqual(db.execute("select count(*) from coaching_events where outcome='FAIL'").fetchone()[0],4)

    def test_budget_and_cloud_disclosure_are_always_zero(self):
        self.controller.ensure_cohort();self.controller.tick()
        job=self.queue.list()[0]
        self.assertEqual(job['priority'],10)
        self.assertEqual(job['max_cost_usd'],0)
        self.assertEqual(job['allow_cloud'],0)
        self.assertEqual(job['external_execution'],0)
        self.assertEqual(job['max_retries'],0)

    def test_daily_limit_and_no_auto_loop_after_done(self):
        limited=CoachingController(self.root/'limited.db',self.queue,source_revision='a'*40,model='fixture-local',clock=self.clock,max_daily_jobs=1)
        limited.ensure_cohort();self.assertEqual(limited.tick(),'SUBMITTED')
        self.complete();limited.tick()
        self.assertEqual(limited.tick(),'DAILY_LIMIT')
        with limited.connect() as db:db.execute("UPDATE coaching_sessions SET state='DONE'")
        self.assertIsNone(limited.ensure_cohort())

    def test_forged_queue_agent_blocks_evaluation(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.queue.connect() as db:db.execute("UPDATE compute_jobs SET agent='a29',status='completed',result='{}'")
        self.assertEqual(self.controller.tick(),'BLOCKED')


if __name__=='__main__':
    unittest.main()
