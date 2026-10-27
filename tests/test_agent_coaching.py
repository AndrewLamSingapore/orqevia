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

    def test_owner_work_does_not_install_a_coaching_queue_guard(self):
        self.controller.ensure_cohort()
        self.queue.submit(agent='a02',prompt='fixture Owner work',priority='critical')
        self.assertEqual(self.controller.tick(),'SUBMITTED')
        self.assertEqual(len(self.queue.list()),2)

    def test_source_change_blocks_resume_instead_of_relabelling_old_work(self):
        self.controller.ensure_cohort()
        newer = CoachingController(self.root/'coaching.db',self.queue,source_revision='b'*40,model='fixture-local',clock=self.clock)
        self.assertEqual(newer.tick(),'SOURCE_SUPERSEDED')
        self.assertEqual(len(self.queue.list()),0)
        with newer.connect() as db:
            row=db.execute("SELECT phase,state,job_id FROM coaching_sessions LIMIT 1").fetchone()
            self.assertEqual((row[0],row[1],row[2]),('baseline','BLOCKED',None))
            outcomes=[r[0] for r in db.execute('SELECT outcome FROM coaching_events ORDER BY event_epoch,rowid')]
            self.assertEqual(outcomes,['SOURCE_SUPERSEDED']*21)
            self.assertEqual(db.execute('SELECT source_revision FROM coaching_cohorts').fetchone()[0],'a'*40)
        self.assertIsNotNone(newer.ensure_cohort())
        self.assertEqual(newer.tick(),'SUBMITTED')
        with newer.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM coaching_sessions s JOIN coaching_cohorts c ON s.cohort_id=c.id WHERE c.source_revision=?",('b'*40,)).fetchone()[0],21)

    def test_source_transition_settles_its_existing_job_without_regrading_or_duplication(self):
        old_cohort=self.controller.ensure_cohort()
        self.assertEqual(self.controller.tick(),'SUBMITTED')
        newer=CoachingController(self.root/'coaching.db',self.queue,source_revision='b'*40,model='fixture-local',clock=self.clock)
        self.assertEqual(newer.tick(),'PRIOR_SOURCE_INFLIGHT')
        self.assertEqual(len(self.queue.list()),1)
        self.complete()
        self.assertEqual(newer.tick(),'SOURCE_SUPERSEDED')
        with newer.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM coaching_sessions WHERE cohort_id=? AND baseline_pass IS NOT NULL",(old_cohort,)).fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM coaching_events WHERE outcome IN ('PASS','FAIL')").fetchone()[0],0)
        self.assertIsNotNone(newer.ensure_cohort())
        self.assertEqual(newer.tick(),'SUBMITTED')
        self.assertEqual(len(self.queue.list()),2)

    def test_recovery_clears_superseded_grades_and_preserves_old_submission_binding(self):
        self.controller.ensure_cohort()
        self.controller.tick()
        self.complete()
        with self.controller.connect() as db:
            row=db.execute("SELECT id,job_key FROM coaching_sessions WHERE state='WAITING'").fetchone()
            session_id,old_key=row['id'],row['job_key']
            db.execute("UPDATE coaching_sessions SET request_sha256='obsolete',baseline_request_sha256='obsolete',baseline_pass=1,practice_pass=1,acceptance_pass=1 WHERE id=?",(session_id,))
        self.assertEqual(self.controller.tick(),'SELF_REPAIRED')
        with self.controller.connect() as db:
            repaired=db.execute('SELECT * FROM coaching_sessions WHERE id=?',(session_id,)).fetchone()
            self.assertIsNone(repaired['baseline_request_sha256'])
            self.assertIsNone(repaired['baseline_pass'])
            self.assertIsNone(repaired['practice_pass'])
            self.assertIsNone(repaired['acceptance_pass'])
            self.assertEqual(repaired['recovery_generation'],1)
        self.assertEqual(self.controller.tick(),'SUBMITTED')
        with self.controller.connect() as db:
            new_key=db.execute('SELECT job_key FROM coaching_sessions WHERE id=?',(session_id,)).fetchone()[0]
        self.assertNotEqual(old_key,new_key)
        with self.queue.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM compute_submission_keys').fetchone()[0],2)

    def test_started_learning_session_reaches_assessment_before_another_baseline(self):
        epoch=[2000000.0]
        self.controller.clock=lambda:epoch[0]
        self.controller.ensure_cohort()
        self.controller.tick()
        first=self.queue.list()[0]['agent']
        for phase in ['practice','practice','acceptance']:
            self.complete()
            epoch[0]+=1
            self.assertEqual(self.controller.tick(),'FAIL')
            self.assertEqual(self.controller.tick(),'SUBMITTED')
            with self.controller.connect() as db:
                row=db.execute("SELECT agent,phase FROM coaching_sessions WHERE state='WAITING'").fetchone()
                self.assertEqual((row['agent'],row['phase']),(first,phase))
        self.complete()
        epoch[0]+=1
        self.controller.tick()
        self.assertEqual(self.controller.tick(),'SUBMITTED')
        with self.controller.connect() as db:
            row=db.execute("SELECT agent,phase FROM coaching_sessions WHERE state='WAITING'").fetchone()
            self.assertNotEqual(row['agent'],first)
            self.assertEqual(row['phase'],'baseline')

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

    def test_probability_cycle_uses_unseen_acceptance_and_retains_only_passed_methods(self):
        from app.probability_curriculum import exercise, LESSONS
        self.controller.ensure_cohort('probability-foundations')
        with self.controller.connect() as db:
            db.execute("UPDATE coaching_sessions SET state='DONE' WHERE agent!='a06'")
        contexts = []
        for phase in ['baseline','practice','acceptance']:
            self.assertEqual(self.controller.tick(),'SUBMITTED')
            with self.controller.connect() as db:
                row = db.execute("SELECT * FROM coaching_sessions WHERE agent='a06'").fetchone()
                self.assertEqual(row['phase'],phase)
            contexts.append(request_for('a06',phase,row['seed'],'probability-foundations')['context'])
            self.complete(json.dumps(exercise('a06',row['seed'],phase)[1]))
            self.assertEqual(self.controller.tick(),'PASS')
        self.assertEqual(len(set(contexts)),3)
        self.assertEqual(self.controller.tick(),'IDLE')
        self.assertIsNone(self.controller.ensure_cohort('probability-foundations'))
        with self.controller.connect() as db:
            records = db.execute('SELECT * FROM academy_retained_methods').fetchall()
            self.assertEqual(len(records),len(LESSONS))
            for method in records:
                event = db.execute('SELECT * FROM coaching_events WHERE id=?',(method['assessment_event_id'],)).fetchone()
                self.assertEqual((event['phase'],event['outcome']),('acceptance','PASS'))
            practice = db.execute("SELECT details_json FROM coaching_events WHERE phase='practice' AND outcome='PASS'").fetchone()
            self.assertEqual(json.loads(practice[0])['academy_record']['wall_seconds'],60)

    def test_performance_gap_reopens_only_affected_completed_role_session(self):
        from app.agent_coaching import record_execution_gap
        self.controller.ensure_cohort()
        with self.controller.connect() as db:
            db.execute("UPDATE coaching_sessions SET state='DONE'")
        # Metadata from an actual terminal job is accepted by the observer;
        # these fixture calls prove policy only, never live agent execution.
        job={'id':'fixture-ordinary','status':'failed','error':'STRICT_JSON_CONTRACT_FAILED',
             'agent':'a06','model':'gemma3:12b'}
        self.assertTrue(record_execution_gap(self.root,job,'a'*40) is False) # different DB path
        canonical = CoachingController(self.root/'agent-coaching.db',self.queue,
            source_revision='a'*40,model='fixture-local',clock=self.clock)
        canonical.ensure_cohort()
        with canonical.connect() as db:
            db.execute("UPDATE coaching_sessions SET state='DONE'")
        self.assertTrue(record_execution_gap(self.root,job,'a'*40))
        self.assertFalse(record_execution_gap(self.root,job,'a'*40))
        self.assertEqual(canonical.observe_performance_gaps(),1)
        self.assertEqual(canonical.observe_performance_gaps(),0)
        with canonical.connect() as db:
            rows=db.execute("SELECT agent FROM coaching_sessions WHERE state='READY'").fetchall()
            self.assertEqual([r['agent'] for r in rows],['a06'])
        self.assertFalse(record_execution_gap(self.root,{**job,'id':'fixture-network','error':'LOCAL_EXECUTION_FAILED'},'a'*40))

    def test_model_mismatch_cannot_receive_a_semantic_grade(self):
        self.controller.ensure_cohort();self.controller.tick();self.complete()
        with self.queue.connect() as db:
            db.execute("UPDATE compute_jobs SET model='different-model'")
        self.assertEqual(self.controller.tick(),'SELF_REPAIRED')
        with self.controller.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM coaching_events WHERE outcome IN ('PASS','FAIL')").fetchone()[0],0)

    def test_budget_and_cloud_disclosure_are_always_zero(self):
        self.controller.ensure_cohort();self.controller.tick()
        job=self.queue.list()[0]
        self.assertEqual(job['priority'],10)
        self.assertEqual(job['max_cost_usd'],0)
        self.assertEqual(job['allow_cloud'],0)
        self.assertEqual(job['external_execution'],0)
        self.assertEqual(job['max_retries'],0)

    def test_executor_notification_requires_verified_https(self):
        self.controller.ensure_cohort();self.controller.tick()
        import ssl
        with patch.dict('os.environ',{'ORQEVIA_COACHING_NOTIFY_ORIGIN':'http://localhost:8443'}):
            with self.assertRaises(ValueError):self.controller.notify_executor()
        with patch.dict('os.environ',{'ORQEVIA_COACHING_NOTIFY_ORIGIN':'https://localhost:8443',
                                      'ORQEVIA_COACHING_CA_FILE':''}),patch('httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value.status_code=200
            self.assertTrue(self.controller.notify_executor())
            context=client.call_args.kwargs['verify']
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertFalse(client.call_args.kwargs['follow_redirects'])

    def test_daily_limit_and_no_auto_loop_after_done(self):
        limited=CoachingController(self.root/'limited.db',self.queue,source_revision='a'*40,model='fixture-local',clock=self.clock,max_daily_jobs=1,cohort_interval_seconds=86400)
        limited.ensure_cohort();self.assertEqual(limited.tick(),'SUBMITTED')
        self.complete();limited.tick()
        self.assertEqual(limited.tick(),'DAILY_LIMIT')
        with limited.connect() as db:db.execute("UPDATE coaching_sessions SET state='DONE'")
        self.assertIsNone(limited.ensure_cohort())

    def test_forged_queue_agent_blocks_evaluation(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.queue.connect() as db:db.execute("UPDATE compute_jobs SET agent='a29',status='completed',result='{}'")
        self.assertEqual(self.controller.tick(),'SELF_REPAIRED')

    def test_storage_limit_includes_wal_before_submission(self):
        limited=CoachingController(self.root/'limited.db',self.queue,source_revision='a'*40,model='fixture-local',clock=self.clock,storage_limit_bytes=64*1024*1024)
        limited.ensure_cohort()
        # Keep an actual WAL alive, as a long-running telemetry reader can do.
        with limited.connect() as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('CREATE TABLE retained_fixture(payload BLOB)')
            writer.execute('INSERT INTO retained_fixture VALUES(zeroblob(?))',(64*1024*1024,))
            writer.commit()
            self.assertLess(limited.path.stat().st_size,64*1024*1024)
            self.assertGreater(Path(str(limited.path)+'-wal').stat().st_size,64*1024*1024)
            self.assertEqual(limited.tick(),'STORAGE_LIMIT')
            self.assertEqual(len(self.queue.list()),0)

    def test_storage_limit_prevents_new_cohort(self):
        limited=CoachingController(self.root/'limited2.db',self.queue,source_revision='a'*40,model='fixture-local',clock=self.clock,storage_limit_bytes=64*1024*1024)
        with limited.connect() as db:
            db.execute('CREATE TABLE retained_fixture(payload BLOB)')
            db.execute('INSERT INTO retained_fixture VALUES(zeroblob(?))',(64*1024*1024,))
        self.assertIsNone(limited.ensure_cohort())
        with limited.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coaching_sessions').fetchone()[0],0)

    def test_missing_submitted_job_blocks_without_replay_or_semantic_grade(self):
        self.controller.ensure_cohort();self.controller.tick()
        with self.queue.connect() as db:
            db.execute('DELETE FROM compute_jobs')
        self.assertEqual(self.controller.tick(),'SELF_REPAIRED')
        with self.controller.connect() as db:
            row=db.execute("SELECT * FROM coaching_sessions WHERE state='READY'").fetchone()
            self.assertIsNotNone(row)
            self.assertIsNone(row['job_id'])
            self.assertIsNone(row['baseline_pass'])
            outcomes=[r[0] for r in db.execute('SELECT outcome FROM coaching_events ORDER BY event_epoch,rowid')]
            self.assertEqual(outcomes,['SUBMITTED','SELF_REPAIRED'])
        self.assertEqual(len(self.queue.list()),0)


if __name__=='__main__':
    unittest.main()
