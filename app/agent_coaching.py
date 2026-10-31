"""Bounded durable coaching controller using the existing single compute queue.

No worker pool, agent identities, external provider, evaluator permissions or
certification are created here. Practice and acceptance remain distinct.
"""
from __future__ import annotations
from contextlib import contextmanager, closing
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
from urllib.parse import urlsplit

from .agent_registry import agent_record, registered_agent_ids
from .home_eco import bounded_setting
from .coaching_exercises import METHODS, VERSION, practice_request, review_practice

PHASES = ('baseline', 'practice', 'acceptance')
STORAGE_LIMIT_BYTES = 512*1024*1024

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def timestamp(epoch):
    return datetime.fromtimestamp(epoch,timezone.utc).isoformat()

def record_execution_gap(root, job, source_revision):
    """Observe an actual output-contract failure; never launch model work here."""
    path = Path(root)/'agent-coaching.db'
    if (not path.is_file() or job.get('status') != 'failed' or
        job.get('error') != 'STRICT_JSON_CONTRACT_FAILED' or
        not job.get('model') or job.get('allow_cloud') or job.get('external_execution') or
        job.get('agent') not in registered_agent_ids(include_orchestrator=False) or
        not re.fullmatch('[a-f0-9]{40}', source_revision or '')):
        return False
    with closing(sqlite3.connect(path, timeout=.2)) as db, db:
        # A backend updated before the controller must not fail normal work.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='coaching_performance_gaps'").fetchone():
            return False
        if db.execute('SELECT 1 FROM coaching_events WHERE job_id=? LIMIT 1', (job['id'],)).fetchone():
            return False
        cursor = db.execute('INSERT OR IGNORE INTO coaching_performance_gaps '
            '(job_id,agent,source_revision,error_code,observed_epoch) VALUES(?,?,?,?,?)',
            (job['id'],job['agent'],source_revision,job['error'],time.time()))
        return cursor.rowcount == 1

def request_for(agent, phase, seed, program='role'):
    if program == 'probability-foundations':
        from .probability_curriculum import assessment_request
        return assessment_request(agent, seed, phase)
    if program != 'role':
        raise ValueError('unknown coaching program')
    if phase == 'practice':
        return practice_request(agent,seed)
    from .agent_cert_role_review import canonical_case_spec
    # Baseline and acceptance use the explicit role:normal_structured case:
    # the v5 answer-free response contract (clarification plus strict JSON
    # schema) rides on the same independent semantic oracle. The legacy
    # request bytes remain intact for historical replay via role:normal.
    return canonical_case_spec(agent,'responsibility.'+agent,'role:normal_structured')['request']

def effective_prompt(agent, phase, seed, feedback=(), program='role'):
    request = request_for(agent,phase,seed,program)
    record = agent_record(agent)
    guide = ('\nReusable method introduced through separate practice: '+METHODS[agent]
             if phase == 'acceptance' and program == 'role' else '')
    prompt = ('Registered role: '+record['name']+'. '+record['purpose']+
              '\nAdvisory synthetic exercise only. No host mutation, external action, deployment, certification or executed-tool claim.'+
              guide+'\nObjective: '+request['objective']+'\nInputs: '+request.get('context',''))
    if phase=='practice' and feedback:
        prompt += '\nPrevious assessment rejected these field contracts: '+', '.join(feedback)+'. Recompute from input facts; no corrected answer is supplied.'
    return request,prompt

class CoachingController:
    def __init__(self, path, queue, *, source_revision, model, clock=time.time,
                 max_daily_jobs=0, max_practice_attempts=2, cohort_interval_seconds=0,
                 storage_limit_bytes=STORAGE_LIMIT_BYTES):
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
        self.storage_limit = storage_limit_bytes
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
              CREATE TABLE IF NOT EXISTS coaching_programs(cohort_id TEXT PRIMARY KEY, program_id TEXT NOT NULL,
                version TEXT NOT NULL, curriculum_sha256 TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS academy_retained_methods(agent TEXT NOT NULL, topic_id TEXT NOT NULL,
                version TEXT NOT NULL, method TEXT NOT NULL, assessment_event_id TEXT NOT NULL,
                assessment_job_id TEXT NOT NULL, source_revision TEXT NOT NULL, retained_epoch REAL NOT NULL,
                PRIMARY KEY(agent,topic_id,version));
              CREATE TABLE IF NOT EXISTS coaching_performance_gaps(job_id TEXT PRIMARY KEY, agent TEXT NOT NULL,
                source_revision TEXT NOT NULL, error_code TEXT NOT NULL, observed_epoch REAL NOT NULL,
                handled_session TEXT);
            ''')
            if 'recovery_generation' not in {row['name'] for row in db.execute('PRAGMA table_info(coaching_sessions)')}:
                db.execute('ALTER TABLE coaching_sessions ADD COLUMN recovery_generation INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def event(self,db,row,outcome,details=None):
        now = self.clock()
        event_id = uuid.uuid4().hex
        db.execute('INSERT INTO coaching_events VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (event_id,row['id'],row['cohort_id'],row['agent'],row['phase'],outcome,
                    timestamp(now),now,row.get('job_id'),self.source,canonical(details or {})))
        return event_id

    def heartbeat(self,state):
        with self.connect() as db:
            db.execute('INSERT INTO coaching_controller VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET source_revision=excluded.source_revision,last_tick_epoch=excluded.last_tick_epoch,state=excluded.state',
                       (self.source,self.clock(),state))

    def notify_executor(self):
        """Notify the existing executor over verified HTTPS after SQLite commit."""
        origin = os.getenv('ORQEVIA_COACHING_NOTIFY_ORIGIN','').rstrip('/')
        if not origin:
            return False  # Existing backend restart recovery remains available.
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('verified HTTPS coaching notification origin required')
        with self.connect() as db:
            row = db.execute("SELECT job_id FROM coaching_sessions WHERE state='WAITING' LIMIT 1").fetchone()
        if row is None or self.queue.get(row['job_id'])['status'] != 'queued':
            return False
        import ssl
        import httpx
        context = ssl.create_default_context(cafile=os.getenv('ORQEVIA_COACHING_CA_FILE') or None)
        try:
            with httpx.Client(verify=context,trust_env=False,follow_redirects=False,timeout=5) as client:
                response = client.post(origin+'/pwa/api/academy/notify/'+row['job_id'],headers={'Origin':origin})
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    def storage_limit_reached(self):
        # A reader can retain uncheckpointed WAL pages while the main file is
        # still small. Count the actual footprint without checkpointing history.
        size = self.path.stat().st_size
        for suffix in ('-wal','-shm'):
            try:
                size += Path(str(self.path)+suffix).stat().st_size
            except FileNotFoundError:
                pass  # SQLite may remove a sidecar after its last reader closes.
        return size >= self.storage_limit

    def self_repair(self, db, row, cause, details=None):
        """Owner-directed maximum autonomy: recoverable stalls reset to a fresh
        baseline run instead of waiting for manual reconciliation."""
        self.event(db, row, 'SELF_REPAIRED', {'cause': cause, **(details or {})})
        db.execute("UPDATE coaching_sessions SET phase='baseline',attempt=1,state='READY',job_id=NULL,"
                   "job_key=NULL,request_sha256=NULL,prompt_sha256=NULL,baseline_request_sha256=NULL,"
                   "baseline_pass=NULL,practice_pass=NULL,acceptance_pass=NULL,feedback_json='[]',"
                   "recovery_generation=recovery_generation+1,updated_epoch=? WHERE id=?",
                   (self.clock(), row['id']))
        return 'SELF_REPAIRED'

    def supersede_source(self, db, row):
        """Retain old provenance, settle owned work, then start a new cohort.

        An in-flight result is never regraded against a different source. This
        checks only this cohort's submitted work; ordinary jobs keep executing.
        """
        pending = [dict(item) for item in db.execute(
            "SELECT * FROM coaching_sessions WHERE cohort_id=? AND state NOT IN ('DONE','BLOCKED')",
            (row['cohort_id'],))]
        for session in pending:
            if not session['job_id']:
                continue
            try:
                job = self.queue.get(session['job_id'])
            except KeyError:
                continue
            if job['status'] not in {'completed','failed','cancelled','budget_blocked'}:
                return 'PRIOR_SOURCE_INFLIGHT'
        for session in pending:
            self.event(db, session, 'SOURCE_SUPERSEDED', {
                'cohort_source':row['source_revision'], 'controller_source':self.source,
                'assessment_performed':False, 'certification_awarded':False})
        db.execute("UPDATE coaching_sessions SET state='BLOCKED',updated_epoch=? "
                   "WHERE cohort_id=? AND state NOT IN ('DONE','BLOCKED')",
                   (self.clock(), row['cohort_id']))
        return 'SOURCE_SUPERSEDED'

    def observe_performance_gaps(self):
        """Reopen only the affected completed role session after a real gap."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            gaps = db.execute('SELECT * FROM coaching_performance_gaps WHERE handled_session IS NULL '
                              'AND source_revision=? ORDER BY observed_epoch LIMIT 21', (self.source,)).fetchall()
            count = 0
            for gap in gaps:
                row = db.execute("SELECT s.* FROM coaching_sessions s JOIN coaching_cohorts c ON c.id=s.cohort_id "
                    "LEFT JOIN coaching_programs p ON p.cohort_id=c.id WHERE s.agent=? AND c.source_revision=? "
                    "AND COALESCE(p.program_id,'role')='role' ORDER BY c.created_epoch DESC LIMIT 1",
                    (gap['agent'],self.source)).fetchone()
                if row is None or row['state'] != 'DONE':
                    continue
                if gap['observed_epoch'] > row['updated_epoch']:
                    self.self_repair(db, dict(row), 'OBSERVED_OUTPUT_CONTRACT_GAP',
                                     {'observed_job_id':gap['job_id'],'error_code':gap['error_code']})
                    count += 1
                db.execute('UPDATE coaching_performance_gaps SET handled_session=? WHERE job_id=?',
                           (row['id'],gap['job_id']))
            return count

    def ensure_cohort(self, program='role'):
        """At most 21 logical sessions per scheduled cohort, never 21 workers."""
        if program not in {'role', 'probability-foundations'}:
            raise ValueError('unknown coaching program')
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
            # Completed learning remains retained. A new program/source or a
            # separately recorded performance gap supplies new work; the monitor
            # does not repeatedly spend inference on unchanged, completed tasks.
            if db.execute("SELECT 1 FROM coaching_cohorts c LEFT JOIN coaching_programs p ON p.cohort_id=c.id "
                          "WHERE c.source_revision=? AND COALESCE(p.program_id,'role')=? LIMIT 1",
                          (self.source, program)).fetchone():
                return None
            last = db.execute('SELECT MAX(created_epoch) FROM coaching_cohorts').fetchone()[0]
            if last is not None and self.clock()-last<self.interval:
                return None
            cohort = uuid.uuid4().hex
            db.execute('INSERT INTO coaching_cohorts VALUES(?,?,?)',(cohort,self.source,self.clock()))
            if program == 'probability-foundations':
                from .probability_curriculum import VERSION as probability_version, catalog
                version, curriculum = probability_version, catalog()
            else:
                version, curriculum = VERSION, {'methods': METHODS, 'version': VERSION}
            db.execute('INSERT INTO coaching_programs VALUES(?,?,?,?)',
                       (cohort, program, version, digest(curriculum)))
            for i,agent in enumerate(agents):
                seed = 1001+i+int(self.clock()//(self.interval or 1))%90000
                db.execute('INSERT INTO coaching_sessions(id,cohort_id,agent,seed,phase,attempt,state,updated_epoch) VALUES(?,?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex,cohort,agent,seed,'baseline',1,'READY',self.clock()))
            return cohort

    def tick(self):
        """One bounded state transition; crash-safe submission uses queue idempotency."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            joined = "SELECT s.*,c.source_revision,COALESCE(p.program_id,'role') AS program_id FROM coaching_sessions s JOIN coaching_cohorts c ON c.id=s.cohort_id LEFT JOIN coaching_programs p ON p.cohort_id=c.id "
            waiting = db.execute(joined+"WHERE s.state='WAITING' ORDER BY s.updated_epoch LIMIT 1").fetchone()
            ready = db.execute(joined+"WHERE s.state='READY' ORDER BY CASE WHEN s.phase='baseline' THEN 1 ELSE 0 END,s.updated_epoch,s.agent LIMIT 1").fetchone()
            row = dict(waiting or ready) if waiting or ready else None
            if row is None: return 'IDLE'
            if self.storage_limit_reached():
                return 'STORAGE_LIMIT'
            if row['source_revision']!=self.source:
                return self.supersede_source(db,row)
            request,prompt = effective_prompt(row['agent'],row['phase'],row['seed'],json.loads(row['feedback_json']),row['program_id'])
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
                         job.get('model')==self.model and
                         job.get('allow_cloud')==0 and job.get('external_execution')==0 and
                         job.get('data_classification')=='LOCAL_ONLY' and job.get('actual_cost_usd',0)==0)
                if not bound:
                    return self.self_repair(db,row,'EXECUTION_BINDING_MISMATCH',{'job_id':row.get('job_id')})
                passed,errors = False,['execution_not_completed']
                if job['status']=='completed':
                    if row['program_id']=='probability-foundations':
                        from .probability_curriculum import review_assessment
                        passed,errors = review_assessment(row['agent'],row['seed'],row['phase'],job.get('result'))
                    elif row['phase']=='practice':
                        passed,errors = review_practice(row['agent'],row['seed'],job.get('result'))
                    else:
                        from .agent_cert_role_review import review_role_output
                        passed,errors = review_role_output(row['agent'],'responsibility.'+row['agent'],job.get('result'))
                # A semantic grade is scoped internal evaluation, never certification.
                evidence = {'passed':bool(passed),'errors':list(errors),'job_status':job['status'],'program_id':row['program_id'],
                            'request_sha256':request_hash,'effective_prompt_sha256':prompt_hash,
                            'result_sha256':hashlib.sha256((job.get('result') or '').encode()).hexdigest(),
                            'job_started_at':job.get('started_at'),'job_completed_at':job.get('completed_at'),
                            'model':job.get('model'),'provider':job.get('provider'),
                            'inference_receipt_present':bool(job.get('inference_receipt')),
                            'certification_awarded':False,'oracle':'existing.role-normal' if row['phase']!='practice' else VERSION}
                if row['program_id']=='probability-foundations':
                    from .academy import Academy
                    from .probability_curriculum import VERSION as probability_version
                    evidence['oracle']='native.'+probability_version
                    academy = Academy()
                    if row['phase']=='practice':
                        try:
                            started = datetime.fromisoformat(job['started_at'].replace('Z','+00:00'))
                            completed = datetime.fromisoformat(job['completed_at'].replace('Z','+00:00'))
                            evidence['academy_record']=academy.submit_training_attempt(row['agent'],'autonomy-safety','s-probability-practice',
                                tokens=int(job.get('input_tokens') or 0)+int(job.get('output_tokens') or 0),
                                wall_seconds=(completed-started).total_seconds(),
                                result={'passed':bool(passed),'error_topics':list(errors)})
                        except (KeyError,TypeError,ValueError):
                            evidence['academy_record']={'status':'UNAVAILABLE','reason':'USAGE_METADATA_UNAVAILABLE'}
                    elif row['phase']=='acceptance':
                        evidence['academy_record']=academy.submit_assessment(row['agent'],'autonomy-safety','s-probability-acceptance',
                            outcome={'passed':bool(passed),'error_topics':list(errors),'certification_awarded':False})
                event_id = self.event(db,row,'PASS' if passed else 'FAIL',evidence)
                if row['program_id']=='probability-foundations' and row['phase']=='acceptance' and passed:
                    from .probability_curriculum import LESSONS, VERSION as probability_version
                    for topic, _, method in LESSONS:
                        db.execute('INSERT INTO academy_retained_methods VALUES(?,?,?,?,?,?,?,?) '
                                   'ON CONFLICT(agent,topic_id,version) DO UPDATE SET method=excluded.method,'
                                   'assessment_event_id=excluded.assessment_event_id,assessment_job_id=excluded.assessment_job_id,'
                                   'source_revision=excluded.source_revision,retained_epoch=excluded.retained_epoch',
                                   (row['agent'],topic,probability_version,method,event_id,job['id'],self.source,self.clock()))
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
            key = ('coaching:'+row['id']+':'+row['phase']+':'+str(row['attempt'])+
                   ':'+str(row['recovery_generation'])+':'+request_hash[:16])
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            # Recover a queue commit that preceded a controller crash. This is
            # readback of our exact submission, not new work bypassing priority.
            with self.queue.connect() as queue_db:
                prior = queue_db.execute('SELECT request_sha256,job_id FROM compute_submission_keys WHERE agent=? AND key_sha256=?',
                    (row['agent'],key_hash)).fetchone()
                # An inconsistent binding is retained as original evidence.
                # A recovery generation gets its own key instead of deleting
                # or reassigning a previously committed submission.
                if prior and prior['request_sha256']!=request_hash:
                    return self.self_repair(db,row,'SUBMISSION_BINDING_CHANGED',
                        {'stale_request_sha256':prior['request_sha256'],'current_request_sha256':request_hash})
            # A session awaits its own result before its next transition. There
            # is no shared-queue admission guard for coaching or ordinary work.
            count = db.execute("SELECT COUNT(*) FROM coaching_events WHERE outcome='SUBMITTED' AND event_epoch>?",(self.clock()-86400,)).fetchone()[0]
            if prior is None and self.daily and count>=self.daily: return 'DAILY_LIMIT'
            if prior is None and db.execute('SELECT COUNT(*) FROM coaching_events').fetchone()[0]>=2000000:
                return 'HISTORY_LIMIT'
            if row['program_id']=='role' and row['phase']=='acceptance' and row['baseline_request_sha256']!=request_hash:
                return self.self_repair(db,row,'ACCEPTANCE_REQUEST_CHANGED')
            job = self.queue.submit(agent=row['agent'],prompt=prompt,priority='background',model_role='deep',model=self.model,
                                    ram_mb=1024,vram_mb=0,timeout_seconds=int(bounded_setting('ORQEVIA_COACHING_EXECUTION_SECONDS',1800,60,7200)),max_retries=0,max_cost_usd=0,
                                    allow_cloud=False,external_execution=False,classification='R0',
                                    data_classification='LOCAL_ONLY',task_class='classification',response_format='strict_json',
                                    response_schema=request.get('response_schema'),idempotency_key=key,
                                    request_digest=request_hash)
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
    # The Owner superseded exclusive model names on 28 October. The controller
    # still binds its configured model and exact request to each assessment;
    # no quality oracle or historical result is weakened or rewritten.
    while not stop.is_set():
        try:
            if (root/'coaching.pause').exists():
                state = 'PAUSED'
            else:
                controller.observe_performance_gaps()
                programs = ['role']
                if os.getenv('ORQEVIA_PROBABILITY_COACHING_ENABLED') == '1':
                    programs.append('probability-foundations')
                for program in programs:
                    if controller.ensure_cohort(program):
                        break
                state = controller.tick()
                if state in {'SUBMITTED','WAITING'}:
                    controller.notify_executor()
            # Fixed state vocabulary only; no exception text, inputs or secrets.
            print(canonical({'component':'agent-coaching','observed_at':timestamp(time.time()),'state':state}),flush=True)
            controller.heartbeat(state)
        except (OSError,sqlite3.Error,ValueError,KeyError):
            state = 'DEPENDENCY_UNAVAILABLE'
            print(canonical({'component':'agent-coaching','observed_at':timestamp(time.time()),'state':'DEPENDENCY_UNAVAILABLE'}),flush=True)
        # State transitions proceed directly; poll active inference without
        # creating another job. Idle monitoring stays inexpensive.
        stop.wait(15 if state in {'IDLE','PAUSED','DEPENDENCY_UNAVAILABLE'} else 1)

if __name__ == '__main__':
    main()
