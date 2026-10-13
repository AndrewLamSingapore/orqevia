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
    def test_process_lock_rejects_overlap_and_releases_after_exit(self):
        from app.agent_coaching import controller_process_lock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'coaching-controller.lock'
            with controller_process_lock(path) as first:
                self.assertTrue(first)
                with controller_process_lock(path) as second:
                    self.assertFalse(second)
            with controller_process_lock(path) as recovered:
                self.assertTrue(recovered)

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

    def test_implementation_revision_does_not_relabel_cohort_evidence(self):
        self.controller.ensure_cohort()
        changed=CoachingController(self.root/'coaching.db',self.queue,
            source_revision='a'*40,implementation_revision='b'*40,model='fixture-local',clock=self.clock)
        self.assertEqual(changed.tick(),'SUBMITTED')
        changed.heartbeat('SUBMITTED')
        with changed.connect() as db:
            event=db.execute('SELECT * FROM coaching_events').fetchone()
            self.assertEqual(event['source_revision'],'a'*40)
            self.assertEqual(json.loads(event['details_json'])['implementation_revision'],'b'*40)
            self.assertEqual(db.execute('SELECT source_revision FROM coaching_controller').fetchone()[0],'b'*40)

    def test_failed_local_null_cost_is_assessed_without_fabricating_cost(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.queue.connect() as db:
            db.execute("UPDATE compute_jobs SET status='failed',actual_cost_usd=NULL WHERE status='queued'")
        self.assertEqual(self.controller.tick(),'FAIL')
        with self.queue.connect() as db:
            self.assertIsNone(db.execute("SELECT actual_cost_usd FROM compute_jobs").fetchone()[0])

    def test_explicit_recovery_preserves_original_block_and_binding(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.controller.connect() as db:
            row=dict(db.execute("SELECT * FROM coaching_sessions WHERE state='WAITING'").fetchone())
            db.execute("UPDATE coaching_sessions SET state='BLOCKED' WHERE id=?",(row['id'],))
            self.controller.event(db,row,'EXECUTION_BINDING_MISMATCH')
        with self.queue.connect() as db:
            db.execute("UPDATE compute_jobs SET status='failed',actual_cost_usd=NULL WHERE id=?",(row['job_id'],))
        self.controller.recover_failed_local_binding(row['id'])
        with self.controller.connect() as db:
            recovered=db.execute('SELECT * FROM coaching_sessions WHERE id=?',(row['id'],)).fetchone()
            self.assertEqual(recovered['job_id'],row['job_id'])
            self.assertEqual(recovered['request_sha256'],row['request_sha256'])
            self.assertEqual(db.execute("SELECT count(*) FROM coaching_events WHERE outcome='EXECUTION_BINDING_MISMATCH'").fetchone()[0],1)
        self.assertEqual(self.controller.tick(),'FAIL')

    def test_null_cost_cannot_authorize_completed_or_external_execution(self):
        for change in ("status='completed'", "status='failed',allow_cloud=1", "status='failed',external_execution=1", "status='failed',data_classification='PUBLIC'"):
            with self.subTest(change=change):
                self.controller.ensure_cohort();self.controller.tick()
                with self.queue.connect() as db:
                    db.execute("UPDATE compute_jobs SET actual_cost_usd=NULL,"+change+" WHERE status='queued'")
                self.assertEqual(self.controller.tick(),'BLOCKED')
                with self.controller.connect() as db:
                    row=db.execute("SELECT id FROM coaching_sessions WHERE state='BLOCKED'").fetchone()
                with self.assertRaises(ValueError):self.controller.recover_failed_local_binding(row['id'])
                # Use independent databases for the next distinct rejection.
                self.temp.cleanup();self.setUp()

    def test_recovery_rejects_changed_contract_and_completed_execution(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.controller.connect() as db:
            row=dict(db.execute("SELECT * FROM coaching_sessions WHERE state='WAITING'").fetchone())
            db.execute("UPDATE coaching_sessions SET state='BLOCKED' WHERE id=?",(row['id'],))
            self.controller.event(db,row,'EXECUTION_BINDING_MISMATCH')
        self.complete()
        with self.assertRaises(ValueError):self.controller.recover_failed_local_binding(row['id'])
        with self.queue.connect() as db:
            db.execute("UPDATE compute_jobs SET status='failed',actual_cost_usd=NULL WHERE id=?",(row['job_id'],))
        with self.controller.connect() as db:
            db.execute("UPDATE coaching_sessions SET request_sha256='changed' WHERE id=?",(row['id'],))
        with self.assertRaises(ValueError):self.controller.recover_failed_local_binding(row['id'])

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

    def test_storage_limit_includes_wal_before_submission(self):
        self.controller.ensure_cohort()
        # Keep an actual WAL alive, as a long-running telemetry reader can do.
        with self.controller.connect() as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE retained_fixture(payload BLOB)')
            writer.execute('INSERT INTO retained_fixture VALUES(zeroblob(?))',(64*1024*1024,))
            writer.commit()
            self.assertLess(self.controller.path.stat().st_size,64*1024*1024)
            self.assertGreater(Path(str(self.controller.path)+'-wal').stat().st_size,64*1024*1024)
            self.assertEqual(self.controller.tick(),'STORAGE_LIMIT')
            self.assertEqual(len(self.queue.list()),0)

    def test_storage_limit_prevents_new_cohort(self):
        with self.controller.connect() as db:
            db.execute('CREATE TABLE retained_fixture(payload BLOB)')
            db.execute('INSERT INTO retained_fixture VALUES(zeroblob(?))',(64*1024*1024,))
        self.assertIsNone(self.controller.ensure_cohort())
        with self.controller.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coaching_sessions').fetchone()[0],0)

    def test_missing_submitted_job_blocks_without_replay_or_semantic_grade(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.queue.connect() as db:
            db.execute('DELETE FROM compute_jobs')
        self.assertEqual(self.controller.tick(),'BLOCKED')
        with self.controller.connect() as db:
            row=db.execute("SELECT * FROM coaching_sessions WHERE state='BLOCKED'").fetchone()
            self.assertIsNotNone(row)
            self.assertIsNotNone(row['job_id'])
            self.assertIsNone(row['baseline_pass'])
            outcomes=[r[0] for r in db.execute('SELECT outcome FROM coaching_events ORDER BY event_epoch,rowid')]
            self.assertEqual(outcomes,['SUBMITTED','QUEUE_JOB_MISSING'])
        self.assertEqual(len(self.queue.list()),0)


if __name__=='__main__':
    unittest.main()
