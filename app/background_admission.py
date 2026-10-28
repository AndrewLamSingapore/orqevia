"""Owner-controlled durable background admission in the existing compute DB.

The database trigger also protects already-running legacy dispatchers. It
ignores only a NEW queued/held -> running transition below interactive priority.
It never cancels active work or alters completed results. No expiry or automatic
resume exists. Resume requires an authenticated caller and current generation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3


SCHEMA = '''
CREATE TABLE IF NOT EXISTS compute_background_admission(
 id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL CHECK(paused IN (0,1)),
 generation INTEGER NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, changed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS compute_background_admission_events(
 generation INTEGER PRIMARY KEY, paused INTEGER NOT NULL, actor TEXT NOT NULL,
 reason TEXT NOT NULL, changed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS compute_background_admission_holds(
 job_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, first_held_at TEXT NOT NULL,
 last_held_at TEXT NOT NULL, hold_count INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS compute_owner_background_admission
BEFORE UPDATE OF status ON compute_jobs
WHEN NEW.status='running' AND OLD.status IN ('queued','held') AND NEW.priority<50
 AND COALESCE((SELECT paused FROM compute_background_admission WHERE id=1),1)=1
BEGIN
 INSERT INTO compute_background_admission_holds
  (job_id,generation,first_held_at,last_held_at,hold_count)
 VALUES(OLD.id,COALESCE((SELECT generation FROM compute_background_admission WHERE id=1),-1),
  strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'),1)
 ON CONFLICT(job_id) DO UPDATE SET generation=excluded.generation,
  last_held_at=excluded.last_held_at,hold_count=hold_count+1;
 SELECT RAISE(IGNORE);
END;
'''


class BackgroundAdmission:
    def __init__(self, db_path):
        self.db_path=str(db_path)

    @contextmanager
    def connect(self, *, readonly=False):
        from pathlib import Path
        target=Path(self.db_path).resolve().as_uri()+'?mode=ro' if readonly else self.db_path
        db=sqlite3.connect(target,uri=readonly,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            if readonly:db.execute('PRAGMA query_only=ON')
            with db:yield db
        finally:db.close()

    @staticmethod
    def read(db):
        try:
            row=db.execute('SELECT * FROM compute_background_admission WHERE id=1').fetchone()
            if row is None:raise ValueError('Missing owner state')
            state=dict(row)
            if state['paused'] not in (0,1):raise ValueError('Invalid owner state')
            return {**state,'paused':bool(state['paused']),'status':'PAUSED' if state['paused'] else 'OPEN'}
        except (sqlite3.Error,ValueError,TypeError):
            return {'paused':True,'generation':None,'status':'UNKNOWN_FAIL_CLOSED',
                    'reason':'Background admission state unavailable'}

    def state(self):
        try:
            with self.connect(readonly=True) as db:
                result=self.read(db)
                result['database_trigger_installed']=bool(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='compute_owner_background_admission'"
                ).fetchone())
                result['holds']=[dict(r) for r in db.execute(
                    'SELECT * FROM compute_background_admission_holds ORDER BY last_held_at DESC LIMIT 64')]
                return result
        except sqlite3.Error:
            return {'paused':True,'generation':None,'status':'UNKNOWN_FAIL_CLOSED',
                    'database_trigger_installed':False,'holds':[]}

    def install_paused(self, *, actor, reason):
        """Explicit Owner installation. No implicit OPEN initialization."""
        self._validate(actor,reason)
        with self.connect() as db:
            # executescript commits implicitly; this script contains only
            # additive tables/trigger. The state transition below is atomic.
            db.executescript(SCHEMA)
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT generation,paused FROM compute_background_admission WHERE id=1').fetchone()
            if row and row['paused']:return self.read(db)
            generation=0 if row is None else row['generation']+1
            self._write(db,True,generation,actor,reason)
        return self.state()

    @staticmethod
    def _validate(actor,reason):
        if not isinstance(actor,str) or not 1<=len(actor)<=128:
            raise ValueError('Authorized actor required')
        if not isinstance(reason,str) or not 1<=len(reason)<=512:
            raise ValueError('Explicit change reason required')

    @staticmethod
    def _write(db,paused,generation,actor,reason):
        ts=datetime.now(timezone.utc).isoformat()
        db.execute('INSERT INTO compute_background_admission VALUES(1,?,?,?,?,?) '
            'ON CONFLICT(id) DO UPDATE SET paused=excluded.paused,generation=excluded.generation,'
            'actor=excluded.actor,reason=excluded.reason,changed_at=excluded.changed_at',
            (int(paused),generation,actor,reason,ts))
        db.execute('INSERT INTO compute_background_admission_events VALUES(?,?,?,?,?)',
                   (generation,int(paused),actor,reason,ts))

    def set_paused(self, paused, *, expected_generation, actor, reason):
        # Authorization belongs to the existing HTTPS API / Owner CLI. A
        # stale response or retry cannot inadvertently resume a newer pause.
        self._validate(actor,reason)
        if type(paused) is not bool or type(expected_generation) is not int:
            raise ValueError('Explicit state and generation required')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state=self.read(db)
            if state['generation']!=expected_generation:
                raise ValueError('Background admission generation changed')
            if state['paused']!=paused:
                self._write(db,paused,expected_generation+1,actor,reason)
        return self.state()

    def verify_transaction(self):
        """Probe the installed trigger with a disposable uncommitted clone.

        No inference or accepted mission is created. All probe rows and hold
        counters roll back, even on failure. Existing mission rows are read
        by SQLite without exporting their prompts/results.
        """
        import uuid
        probe='admission-probe-'+uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                state=self.read(db)
                if state['status']!='PAUSED':
                    raise ValueError('Verification requires an explicit paused state')
                columns=[r['name'] for r in db.execute('PRAGMA table_info(compute_jobs)')]
                if not columns or any(not name.replace('_','').isalnum() for name in columns):
                    raise ValueError('Unexpected compute schema')
                replacements={'id':'?','status':"'queued'",'priority':'10','attempts':'0'}
                expressions=','.join(replacements.get(c,c) for c in columns)
                changed=db.execute('INSERT INTO compute_jobs ('+','.join(columns)+') '
                    'SELECT '+expressions+' FROM compute_jobs LIMIT 1',(probe,))
                if changed.rowcount!=1:raise ValueError('No source row for admission probe')
                blocked=db.execute("UPDATE compute_jobs SET status='running',attempts=attempts+1 WHERE id=?",(probe,)).rowcount==0
                waiting=db.execute('SELECT status,attempts FROM compute_jobs WHERE id=?',(probe,)).fetchone()
                db.execute('UPDATE compute_jobs SET priority=50 WHERE id=?',(probe,))
                interactive=db.execute("UPDATE compute_jobs SET status='running' WHERE id=?",(probe,)).rowcount==1
                result={'background_transition_blocked':blocked,
                        'background_remains_queued':waiting['status']=='queued' and waiting['attempts']==0,
                        'interactive_transition_allowed':interactive,'generation':state['generation'],
                        'physical_inference_calls':0,'probe_transaction_rolled_back':True}
            finally:db.rollback()
        return result
