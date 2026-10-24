"""Bounded durable coaching controller using the existing single compute queue.

No worker pool, agent identities, external provider, evaluator permissions or
certification are created here. Practice and acceptance remain distinct.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import threading
import time
import uuid

from .agent_registry import agent_record, registered_agent_ids
from .coaching_exercises import METHODS, VERSION, practice_request, review_practice

PHASES = ('baseline', 'practice', 'acceptance')
STORAGE_LIMIT_BYTES = 512*1024*1024

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def timestamp(epoch):
    return datetime.fromtimestamp(epoch,timezone.utc).isoformat()

def request_for(agent, phase, seed):
    if phase == 'practice':
        return practice_request(agent,seed)
    from .agent_cert_role_review import canonical_case_spec
    # Baseline and acceptance use the explicit role:normal_structured case:
    # the v5 answer-free response contract (clarification plus strict JSON
    # schema) rides on the same independent semantic oracle. The legacy
    # request bytes remain intact for historical replay via role:normal.
    return canonical_case_spec(agent,'responsibility.'+agent,'role:normal_structured')['request']

def effective_prompt(agent, phase, seed, feedback=()):
    request = request_for(agent,phase,seed)
    record = agent_record(agent)
    guide = ('\nReusable method introduced through separate practice: '+METHODS[agent]
             if phase == 'acceptance' else '')
    prompt = ('Registered role: '+record['name']+'. '+record['purpose']+
              '\nAdvisory synthetic exercise only. No host mutation, external action, deployment, certification or executed-tool claim.'+
              guide+'\nObjective: '+request['objective']+'\nInputs: '+request.get('context',''))
    if phase=='practice' and feedback:
        prompt += '\nPrevious assessment rejected these field contracts: '+', '.join(feedback)+'. Recompute from input facts; no corrected answer is supplied.'
    return request,prompt

class CoachingController:
    def __init__(self, path, queue, *, source_revision, model, clock=time.time,
                 max_daily_jobs=0, max_practice_attempts=2, cohort_interval_seconds=0):
        if not re.fullmatch('[a-f0-9]{40}',source_revision):
            raise ValueError('pinned coaching source revision required')
        if not model or len(model)>128:
            raise ValueError('existing local model required')
        if type(max_daily_jobs) is not int or not 0<=max_daily_jobs<=100000000:
            raise ValueError('bounded daily job limit required')
        if max_practice_attempts not in (1,2) or cohort_interval_seconds<0:
            raise ValueError('bounded retry policy required; cohort interval may be zero (resume immediately)')
        self.path,self.queue = Path(path),queue
        self.source,self.model,self.clock = source_revision,model,clock
        self.daily,self.attempts,self.interval = max_daily_jobs,max_practice_attempts,cohort_interval_seconds
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS coaching_cohorts(id TEXT PRIMARY KEY, source_revision TEXT NOT NULL, created_epoch REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS coaching_sessions(id TEXT PRIMARY KEY, cohort_id TEXT NOT NULL, agent TEXT NOT NULL, seed INTEGER NOT NULL,
                phase TEXT NOT NULL, attempt INTEGER NOT NULL, state TEXT NOT NULL, job_id TEXT, job_key TEXT, request_sha256 TEXT,
                prompt_sha256 TEXT, baseline_request_sha256 TEXT, baseline_pass INTEGER, acceptance_pass INTEGER, practice_pass INTEGER,
                feedback_json TEXT NOT NULL DEFAULT '[]', updated_epoch REAL NOT NULL, UNIQUE(cohort_id,agent));
              CREATE TABLE IF NOT EXISTS coaching_events(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, correlation_id TEXT NOT NULL,
                agent TEXT NOT NULL, phase TEXT NOT NULL, outcome TEXT NOT NULL, timestamp TEXT NOT NULL, event_epoch REAL NOT NULL,
                job_id TEXT, source_revision TEXT NOT NULL, details_json TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS coaching_due ON coaching_sessions(state,updated_epoch);
              CREATE INDEX IF NOT EXISTS coaching_history ON coaching_events(event_epoch);
              CREATE TABLE IF NOT EXISTS coaching_controller(id INTEGER PRIMARY KEY CHECK(id=1), source_revision TEXT NOT NULL,
                last_tick_epoch REAL NOT NULL, state TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def event(self,db,row,outcome,details=None):
        now = self.clock()
        db.execute('INSERT INTO coaching_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (uuid.uuid4().hex,row['id'],row['cohort_id'],row['agent'],row['phase'],outcome,
                    timestamp(now),now,row.get('job_id'),self.source,canonical(details or {})))

    def heartbeat(self,state):
        with self.connect() as db:
            db.execute('INSERT INTO coaching_controller VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET source_revision=excluded.source_revision,last_tick_epoch=excluded.last_tick_epoch,state=excluded.state',
                       (self.source,self.clock(),state))

    def storage_limit_reached(self):
        # A reader can retain uncheckpointed WAL pages while the main file is
        # still small. Count the actual footprint without checkpointing history.
        size = self.path.stat().st_size
        for suffix in ('-wal','-shm'):
            try:
                size += Path(str(self.path)+suffix).stat().st_size
            except FileNotFoundError:
                pass  # SQLite may remove a sidecar after its last reader closes.
        return size >= STORAGE_LIMIT_BYTES

    def self_repair(self, db, row, cause, details=None):
        """Owner-directed maximum autonomy: recoverable stalls reset to a fresh
        baseline run instead of waiting for manual reconciliation."""
        self.event(db, row, 'SELF_REPAIRED', {'cause': cause, **(details or {})})
        db.execute("UPDATE coaching_sessions SET phase='baseline',attempt=1,state='READY',job_id=NULL,"
                   "job_key=NULL,request_sha256=NULL,prompt_sha256=NULL,feedback_json='[]',updated_epoch=? WHERE id=?",
                   (self.clock(), row['id']))
        return 'SELF_REPAIRED'

    def ensure_cohort(self):
        """At most 21 logical sessions per scheduled cohort, never 21 workers."""
        agents = sorted(registered_agent_ids(include_orchestrator=False))
        if set(agents)!=set(METHODS):
            raise ValueError('practice coverage does not match canonical registry')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.storage_limit_reached():
                return None
            if db.execute('SELECT COUNT(*) FROM coaching_events').fetchone()[0]>=2000000:
                return None
            if db.execute("SELECT 1 FROM coaching_sessions WHERE state NOT IN ('DONE','BLOCKED') LIMIT 1").fetchone():
                return None
            last = db.execute('SELECT MAX(created_epoch) FROM coaching_cohorts').fetchone()[0]
            if last is not None and self.clock()-last<self.interval:
                return None
            cohort = uuid.uuid4().hex
            db.execute('INSERT INTO coaching_cohorts VALUES(?,?,?)',(cohort,self.source,self.clock()))
            for i,agent in enumerate(agents):
                seed = 1001+i+int(self.clock()//(self.interval or 1))%90000
                db.execute('INSERT INTO coaching_sessions(id,cohort_id,agent,seed,phase,attempt,state,updated_epoch) VALUES(?,?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex,cohort,agent,seed,'baseline',1,'READY',self.clock()))
            return cohort

    def tick(self):
        """One bounded state transition; crash-safe submission uses queue idempotency."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            waiting = db.execute("SELECT s.*,c.source_revision FROM coaching_sessions s JOIN coaching_cohorts c ON c.id=s.cohort_id WHERE s.state='WAITING' ORDER BY s.updated_epoch LIMIT 1").fetchone()
            ready = db.execute("SELECT s.*,c.source_revision FROM coaching_sessions s JOIN coaching_cohorts c ON c.id=s.cohort_id WHERE s.state='READY' ORDER BY s.updated_epoch,s.agent LIMIT 1").fetchone()
            row = dict(waiting or ready) if waiting or ready else None
            if row is None: return 'IDLE'
            if self.storage_limit_reached():
                return 'STORAGE_LIMIT'
            if row['source_revision']!=self.source:
                return self.self_repair(db,row,'SOURCE_CHANGED',
                    {'cohort_source':row['source_revision'],'controller_source':self.source})
            request,prompt = effective_prompt(row['agent'],row['phase'],row['seed'],json.loads(row['feedback_json']))
            request_hash,prompt_hash = digest(request),hashlib.sha256(prompt.encode()).hexdigest()
            if waiting:
                if row['request_sha256']!=request_hash or row['prompt_sha256']!=prompt_hash:
                    return self.self_repair(db,row,'CONTRACT_CHANGED')
                try:
                    job = self.queue.get(row['job_id'])
                except KeyError:
                    return self.self_repair(db,row,'QUEUE_JOB_MISSING',{'job_id':row.get('job_id')})
                if job['status'] not in {'completed','failed','cancelled','budget_blocked'}:
                    return 'WAITING'
                bound = (job.get('agent')==row['agent'] and job.get('prompt')==prompt and
                         job.get('allow_cloud')==0 and job.get('external_execution')==0 and
                         job.get('data_classification')=='LOCAL_ONLY' and job.get('actual_cost_usd',0)==0)
                if not bound:
                    return self.self_repair(db,row,'EXECUTION_BINDING_MISMATCH',{'job_id':row.get('job_id')})
                passed,errors = False,['execution_not_completed']
                if job['status']=='completed':
                    if row['phase']=='practice':
                        passed,errors = review_practice(row['agent'],row['seed'],job.get('result'))
                    else:
                        from .agent_cert_role_review import review_role_output
                        passed,errors = review_role_output(row['agent'],'responsibility.'+row['agent'],job.get('result'))
                # A semantic grade is scoped internal evaluation, never certification.
                evidence = {'passed':bool(passed),'errors':list(errors),'job_status':job['status'],
                            'request_sha256':request_hash,'effective_prompt_sha256':prompt_hash,
                            'result_sha256':hashlib.sha256((job.get('result') or '').encode()).hexdigest(),
                            'job_started_at':job.get('started_at'),'job_completed_at':job.get('completed_at'),
                            'model':job.get('model'),'provider':job.get('provider'),
                            'inference_receipt_present':bool(job.get('inference_receipt')),
                            'certification_awarded':False,'oracle':'existing.role-normal' if row['phase']!='practice' else VERSION}
                self.event(db,row,'PASS' if passed else 'FAIL',evidence)
                column = row['phase']+'_pass'
                db.execute('UPDATE coaching_sessions SET '+column+'=? WHERE id=?',(int(passed),row['id']))
                if row['phase']=='practice' and not passed and row['attempt']<self.attempts:
                    next_phase,next_attempt,state = 'practice',row['attempt']+1,'READY'
                elif row['phase']=='acceptance':
                    next_phase,next_attempt,state = 'acceptance',row['attempt'],'DONE'
                else:
                    next_phase,next_attempt,state = PHASES[PHASES.index(row['phase'])+1],1,'READY'
                # Fixed assessor field names only; no expected values/model text.
                feedback = [e for e in errors if re.fullmatch('[a-zA-Z0-9_.:-]{1,100}',e)][:32]
                db.execute('UPDATE coaching_sessions SET phase=?,attempt=?,state=?,job_id=NULL,job_key=NULL,feedback_json=?,updated_epoch=? WHERE id=?',
                           (next_phase,next_attempt,state,canonical(feedback),self.clock(),row['id']))
                return 'PASS' if passed else 'FAIL'
            key = 'coaching:'+row['id']+':'+row['phase']+':'+str(row['attempt'])
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            # Recover a queue commit that preceded a controller crash. This is
            # readback of our exact submission, not new work bypassing priority.
            with self.queue.connect() as queue_db:
                prior = queue_db.execute('SELECT request_sha256,job_id FROM compute_submission_keys WHERE agent=? AND key_sha256=?',
                    (row['agent'],key_hash)).fetchone()
                # A case-spec repair can change the request behind an old
                # controller-owned key. The stale binding's job is terminal
                # history; reconcile the key now instead of failing forever.
                if prior and prior['request_sha256']!=request_hash:
                    queue_db.execute('DELETE FROM compute_submission_keys WHERE agent=? AND key_sha256=?',(row['agent'],key_hash))
                    self.event(db,{**row,'job_id':prior['job_id']},'STALE_BINDING_RECONCILED',
                        {'stale_request_sha256':prior['request_sha256'],'current_request_sha256':request_hash})
                    prior = None
            # One coaching job at a time. Ordinary/Owner work precedes new practice.
            if prior is None and (self.queue.list(status='queued',limit=1) or self.queue.list(status='running',limit=1)):
                return 'OWNER_QUEUE_BUSY'
            count = db.execute("SELECT COUNT(*) FROM coaching_events WHERE outcome='SUBMITTED' AND event_epoch>?",(self.clock()-86400,)).fetchone()[0]
            if prior is None and self.daily and count>=self.daily: return 'DAILY_LIMIT'
            if prior is None and db.execute('SELECT COUNT(*) FROM coaching_events').fetchone()[0]>=2000000:
                return 'HISTORY_LIMIT'
            if row['phase']=='acceptance' and row['baseline_request_sha256']!=request_hash:
                return self.self_repair(db,row,'ACCEPTANCE_REQUEST_CHANGED')
            job = self.queue.submit(agent=row['agent'],prompt=prompt,priority='background',model_role='deep',model=self.model,
                                    ram_mb=1024,vram_mb=0,timeout_seconds=300,max_retries=0,max_cost_usd=0,
                                    allow_cloud=False,external_execution=False,classification='R0',
                                    data_classification='LOCAL_ONLY',task_class='classification',response_format='strict_json',
                                    response_schema=request.get('response_schema'),idempotency_key=key)
            db.execute("UPDATE coaching_sessions SET state='WAITING',job_id=?,job_key=?,request_sha256=?,prompt_sha256=?,baseline_request_sha256=COALESCE(baseline_request_sha256,?),updated_epoch=? WHERE id=?",
                       (job['id'],key,request_hash,prompt_hash,request_hash if row['phase']=='baseline' else None,self.clock(),row['id']))
            self.event(db,{**row,'job_id':job['id']},'SUBMITTED',{'request_sha256':request_hash,'effective_prompt_sha256':prompt_hash,'max_cost_usd':0})
            return 'SUBMITTED'

def main():
    from .compute_queue_api import queue
    from .settings import SETTINGS
    stop = threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stop.set())
    root = Path(os.getenv('ORQEVIA_DATA_DIR','/data'))
    controller = CoachingController(root/'agent-coaching.db',queue,
        source_revision=os.environ['ORQEVIA_COACHING_SOURCE_REVISION'],model=SETTINGS.deep_model)
    while not stop.is_set():
        try:
            if (root/'coaching.pause').exists():
                state = 'PAUSED'
            else:
                controller.ensure_cohort()
                state = controller.tick()
            # Fixed state vocabulary only; no exception text, inputs or secrets.
            print(canonical({'component':'agent-coaching','observed_at':timestamp(time.time()),'state':state}),flush=True)
            controller.heartbeat(state)
        except (OSError,sqlite3.Error,ValueError,KeyError):
            print(canonical({'component':'agent-coaching','observed_at':timestamp(time.time()),'state':'DEPENDENCY_UNAVAILABLE'}),flush=True)
        stop.wait(15)

if __name__ == '__main__':
    main()
