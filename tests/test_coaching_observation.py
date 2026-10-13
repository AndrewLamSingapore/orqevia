import sqlite3
from pathlib import Path
import tempfile
import unittest
from app.agent_coaching import CoachingController
from app.job_queue import JobQueue
from app.coaching_observation import coaching_snapshot

class ObservationTests(unittest.TestCase):
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

    def test_partial_registry_records_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);queue=JobQueue(root/'queue.db')
            controller=CoachingController(root/'agent-coaching.db',queue,source_revision='a'*40,model='fixture')
            controller.ensure_cohort()
            with controller.connect() as db:db.execute("delete from coaching_sessions where agent='a01'")
            self.assertEqual(coaching_snapshot(root)['status'],'UNAVAILABLE')

if __name__=='__main__':unittest.main()
