"""Bounded read-only historical coaching aggregates; no task text or credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

def coaching_snapshot(root, now=None):
    path = Path(root)/'agent-coaching.db'
    unavailable = {'status':'UNAVAILABLE','last_event_at':None,'cohort_source_revision':None,
                   'assessment_scope':'INTERNAL_ROLE_ASSESSMENT_ONLY','certification_awarded':False,
                   'agents':[],'baseline_pass_count':None,'acceptance_pass_count':None,'completed_count':None,
                   'controller':{'availability':'UNKNOWN','last_tick_at':None,'source_revision':None,'last_state':None}}
    if not path.is_file(): return unavailable
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic()+.2
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        cohort = db.execute('SELECT id,source_revision FROM coaching_cohorts ORDER BY created_epoch DESC LIMIT 1').fetchone()
        if not cohort: return unavailable
        program = 'role'
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='coaching_programs'").fetchone():
            metadata = db.execute('SELECT program_id FROM coaching_programs WHERE cohort_id=?',(cohort['id'],)).fetchone()
            if metadata:
                program = metadata['program_id']
        rows = db.execute('SELECT agent,phase,state,baseline_pass,practice_pass,acceptance_pass,updated_epoch FROM coaching_sessions WHERE cohort_id=? LIMIT 22',(cohort['id'],)).fetchall()
        from .agent_registry import registered_agent_ids
        if len(rows)!=21 or {r['agent'] for r in rows}!=registered_agent_ids(include_orchestrator=False):
            return unavailable
        last = db.execute('SELECT MAX(event_epoch) FROM coaching_events WHERE correlation_id=?',(cohort['id'],)).fetchone()[0]
        now = datetime.now(timezone.utc).timestamp() if now is None else now
        heartbeat = db.execute('SELECT source_revision,last_tick_epoch,state FROM coaching_controller WHERE id=1').fetchone()
        controller = dict(unavailable['controller'])
        if heartbeat:
            age = now-heartbeat['last_tick_epoch']
            controller = {'availability':'UNKNOWN' if age < -5 else ('STALE' if age>60 else 'OBSERVED'),
                          'last_tick_at':datetime.fromtimestamp(heartbeat['last_tick_epoch'],timezone.utc).isoformat(),
                          'source_revision':heartbeat['source_revision'],'last_state':heartbeat['state']}
        status = 'UNKNOWN' if last is None or last>now+5 else ('STALE' if now-last>60 else 'OBSERVED')
        return {**unavailable,'status':status,'last_event_at':datetime.fromtimestamp(last,timezone.utc).isoformat() if last is not None else None,
                'program_id':program,
                'assessment_scope':'INTERNAL_PROBABILITY_ASSESSMENT_ONLY' if program=='probability-foundations' else 'INTERNAL_ROLE_ASSESSMENT_ONLY',
                'cohort_source_revision':cohort['source_revision'],'cohort_id':cohort['id'],'controller':controller,
                'baseline_pass_count':sum(r['baseline_pass']==1 for r in rows),
                'acceptance_pass_count':sum(r['acceptance_pass']==1 for r in rows),
                'completed_count':sum(r['state']=='DONE' for r in rows),
                'agents':[{'agent_id':r['agent'],'phase':r['phase'],'state':r['state'],
                           'baseline_pass':None if r['baseline_pass'] is None else bool(r['baseline_pass']),
                           'practice_pass':None if r['practice_pass'] is None else bool(r['practice_pass']),
                           'acceptance_pass':None if r['acceptance_pass'] is None else bool(r['acceptance_pass']),
                           'last_transition_at':datetime.fromtimestamp(r['updated_epoch'],timezone.utc).isoformat()} for r in rows]}
    except (OSError,sqlite3.Error,ValueError,TypeError,OverflowError):
        return unavailable
    finally:
        if db is not None: db.close()
