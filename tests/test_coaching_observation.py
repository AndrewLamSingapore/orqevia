import sqlite3
from pathlib import Path
import tempfile
import unittest
from app.agent_coaching import CoachingController
from app.job_queue import JobQueue
from app.coaching_observation import coaching_snapshot

class ObservationTests(unittest.TestCase):
    def test_original_failure_scores_actions_and_full_acceptance_stay_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);queue=JobQueue(root/'queue.db')
            c=CoachingController(root/'agent-coaching.db',queue,source_revision='a'*40,model='fixture',clock=lambda:1000000.0)
            c.ensure_cohort()
            with c.connect() as db:
                row=dict(db.execute("SELECT * FROM coaching_sessions WHERE agent='a13'").fetchone())
                db.execute("UPDATE coaching_sessions SET baseline_pass=0,acceptance_pass=1,phase='acceptance',state='DONE' WHERE id=?",(row['id'],))
                c.event(db,row,'FAIL',{'errors':['execution_not_completed'],'prompt':'PRIVATE_PROMPT','secret':'PRIVATE_CREDENTIAL'})
                c.event(db,{**row,'phase':'practice'},'SUBMITTED')
                c.event(db,{**row,'phase':'acceptance'},'PASS',{'errors':[]})
            report=coaching_snapshot(root,now=1000010)
            agent=next(x for x in report['agents'] if x['agent_id']=='a13')
            self.assertEqual(agent['baseline_score'],0)
            self.assertEqual(agent['latest_score'],100)
            self.assertEqual(agent['failures'][0]['errors'],['execution_not_completed'])
            self.assertEqual(agent['coaching_actions'][0]['action'],'practice_submitted')
            self.assertEqual(agent['reassessment_results'][0]['outcome'],'PASS')
            self.assertEqual(agent['full_role_acceptance_status'],'NOT_ESTABLISHED')
            self.assertNotIn('PRIVATE_PROMPT',str(report))
            self.assertNotIn('PRIVATE_CREDENTIAL',str(report))

    def test_missing_database_is_not_zero_or_newly_observed(self):
        with tempfile.TemporaryDirectory() as root:
            report = coaching_snapshot(root)
            self.assertEqual(report['status'],'UNAVAILABLE')
            self.assertIsNone(report['acceptance_pass_count'])
            self.assertFalse((Path(root)/'agent-coaching.db').exists())

    def test_old_event_time_survives_new_reconciliation_and_read_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue = JobQueue(root/'queue.db')
            controller = CoachingController(root/'agent-coaching.db',queue,source_revision='a'*40,model='fixture',clock=lambda:1000000.0)
            controller.ensure_cohort();controller.tick()
            before = (root/'agent-coaching.db').read_bytes()
            old = coaching_snapshot(root,now=2000000)
            self.assertEqual(old['status'],'STALE')
            self.assertEqual(old['last_event_at'],'1970-01-12T13:46:40+00:00')
            self.assertEqual(len(old['agents']),21)
            self.assertIsNone(old['agents'][0]['acceptance_pass'])
            self.assertEqual(before,(root/'agent-coaching.db').read_bytes())
            fresh = coaching_snapshot(root,now=1000010)
            self.assertEqual(fresh['status'],'OBSERVED')
            self.assertFalse(fresh['certification_awarded'])
            self.assertNotIn('prompt',str(fresh))
            self.assertNotIn('result_sha256',str(fresh))

    def test_controller_heartbeat_is_distinct_from_original_assessment_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);queue=JobQueue(root/'queue.db')
            controller=CoachingController(root/'agent-coaching.db',queue,source_revision='a'*40,model='fixture',clock=lambda:1000000.0)
            controller.ensure_cohort();controller.tick()
            original=coaching_snapshot(root,now=2000000)['last_event_at']
            controller.clock=lambda:2000000.0
            controller.heartbeat('DAILY_LIMIT')
            report=coaching_snapshot(root,now=2000010)
            self.assertEqual(report['controller']['availability'],'OBSERVED')
            self.assertEqual(report['last_event_at'],original)
            self.assertEqual(report['status'],'STALE')
            self.assertEqual(coaching_snapshot(root,now=2000070)['controller']['availability'],'STALE')

    def test_partial_registry_records_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);queue=JobQueue(root/'queue.db')
            controller=CoachingController(root/'agent-coaching.db',queue,source_revision='a'*40,model='fixture')
            controller.ensure_cohort()
            with controller.connect() as db:db.execute("delete from coaching_sessions where agent='a01'")
            self.assertEqual(coaching_snapshot(root)['status'],'UNAVAILABLE')

if __name__=='__main__':unittest.main()
