"""Bounded read-only historical coaching aggregates; no task text or credentials."""
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sqlite3
import time

def agent_coaching_details(db, cohort_id, row):
    """Bounded original assessment fields, never prompts, results or credentials."""
    events = db.execute('SELECT phase,outcome,timestamp,details_json FROM coaching_events WHERE correlation_id=? AND agent=? ORDER BY event_epoch DESC,rowid DESC LIMIT 64',
                        (cohort_id,row['agent'])).fetchall()
    assessments=[];failures=[];actions=[]
    for event in events:
        phase,outcome,at,raw=event
        if outcome in ('PASS','FAIL'):
            details=json.loads(raw)
            errors=details.get('errors',[])
            errors=[x for x in errors[:64] if type(x) is str and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,96}',x)] if type(errors) is list else []
            assessment={'phase':phase,'outcome':outcome,'assessed_at':at,'errors':errors}
            assessments.append(assessment)
            if outcome=='FAIL':failures.append(assessment)
        elif outcome=='SUBMITTED' and phase=='practice':
            actions.append({'action':'practice_submitted','at':at})
        elif outcome=='FAILED_LOCAL_BINDING_RECOVERED':
            actions.append({'action':'retained_failed_local_binding_recovered','at':at})
    from .agent_registry import agent_record
    from .coaching_exercises import METHODS
    latest=assessments[0] if assessments else None
    baseline=row['baseline_pass']
    return {'role':agent_record(row['agent'])['name'],
            'score_scale':'SINGLE_SYNTHETIC_CASE_BINARY_0_OR_100_NOT_ROLE_COMPETENCE',
            'baseline_score':None if baseline is None else (100 if baseline==1 else 0),
            'latest_score':None if latest is None else (100 if latest['outcome']=='PASS' else 0),
            'latest_assessment_at':latest['assessed_at'] if latest else None,
            'last_activity_at':events[0]['timestamp'] if events else None,
            'failures':failures,'coaching_actions':actions,
            'coaching_method':METHODS[row['agent']] if actions else None,
            'reassessment_results':[x for x in assessments if x['phase']=='acceptance'],
            'full_role_acceptance_status':'NOT_ESTABLISHED',
            'blocker':events[0]['outcome'] if row['state']=='BLOCKED' and events else None}

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
        db.execute('BEGIN')
        deadline = time.monotonic()+.2
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        cohort = db.execute('SELECT id,source_revision FROM coaching_cohorts ORDER BY created_epoch DESC LIMIT 1').fetchone()
        if not cohort: return unavailable
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
                'cohort_source_revision':cohort['source_revision'],'cohort_id':cohort['id'],'controller':controller,
                'baseline_pass_count':sum(r['baseline_pass']==1 for r in rows),
                'acceptance_pass_count':sum(r['acceptance_pass']==1 for r in rows),
                'completed_count':sum(r['state']=='DONE' for r in rows),
                'agents':[{'agent_id':r['agent'],'phase':r['phase'],'state':r['state'],
                           'baseline_pass':None if r['baseline_pass'] is None else bool(r['baseline_pass']),
                           'practice_pass':None if r['practice_pass'] is None else bool(r['practice_pass']),
                           'acceptance_pass':None if r['acceptance_pass'] is None else bool(r['acceptance_pass']),
                           'last_transition_at':datetime.fromtimestamp(r['updated_epoch'],timezone.utc).isoformat(),
                           **agent_coaching_details(db,cohort['id'],r)} for r in rows]}
    except (OSError,sqlite3.Error,ValueError,TypeError,OverflowError):
        return unavailable
    finally:
        if db is not None: db.close()
