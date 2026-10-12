from contextlib import closing
"""Read-only aggregate projection shared by legacy health and the PWA telemetry contract."""
import os,json,re,sqlite3,time
from pathlib import Path
from .agent_registry import load_agent_registry

def _observed_count(path: Path, query: str, parameters=()):
    if not path.is_file():
        return {'status':'UNAVAILABLE','count':None}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
            deadline = time.monotonic() + 1
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            return {'status':'OBSERVED','count':db.execute(query,parameters).fetchone()[0]}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        return {'status':'UNAVAILABLE','count':None}


def evidence_aggregates():
    """Safe aggregate evidence from the active direct-execution stores only."""
    root=Path(os.getenv('PRIME_DATA_DIR','/data')).resolve()
    registry=load_agent_registry()
    objectives=_observed_count(root/'objectives.db','SELECT COUNT(*) FROM objectives')
    jobs=_observed_count(root/'compute-queue.db','SELECT COUNT(*) FROM compute_jobs')
    sessions={'status':'UNAVAILABLE','stored_count':None,'non_revoked_count':None,'active_count':None}
    try:
        path=root/'pwa-sessions.db'
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                stored,non_revoked,active=db.execute(
                    'SELECT COUNT(*),SUM(CASE WHEN revoked=0 THEN 1 ELSE 0 END),'
                    'SUM(CASE WHEN revoked=0 AND expires>? THEN 1 ELSE 0 END) FROM sessions',
                    (time.time(),)).fetchone()
            sessions={'status':'OBSERVED','stored_count':stored,
                'non_revoked_count':non_revoked or 0,'active_count':active or 0,
                'active_scope':'Non-revoked sessions whose expiry is in the future'}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        pass

    job_states={'status':'UNAVAILABLE','counts':{}}
    try:
        path=root/'compute-queue.db'
        if path.is_file():
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                rows=db.execute('SELECT status,COUNT(*) FROM compute_jobs GROUP BY status').fetchall()
            job_states={'status':'OBSERVED','counts':{str(state):count for state,count in rows}}
    except (OSError,sqlite3.Error,TypeError,ValueError):
        pass

    artifacts={'status':'UNAVAILABLE','count':None}
    try:
        store=root/'artifacts'
        if store.is_dir():
            count=0
            for folder in store.iterdir():
                if not folder.is_dir() or not re.fullmatch(r'[0-9a-f]{32}',folder.name):continue
                metadata=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
                if metadata.get('artifact_id')==folder.name:count+=1
            artifacts={'status':'OBSERVED','count':count}
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        artifacts={'status':'UNAVAILABLE','count':None}

    actions={'status':'UNAVAILABLE','count':None}
    try:
        path=root/'action-records.jsonl'
        if path.is_file():
            count=0
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    value=json.loads(line)
                    if isinstance(value,dict) and isinstance(value.get('sequence'),int):count+=1
            actions={'status':'OBSERVED','count':count}
    except (OSError,ValueError,TypeError,json.JSONDecodeError):
        actions={'status':'UNAVAILABLE','count':None}

    revision=os.getenv('PRIME_INTERFACE_RUNTIME_REVISION','UNKNOWN').strip().lower()
    if revision!='UNKNOWN' and not re.fullmatch(r'[0-9a-f]{40}',revision):revision='UNKNOWN'
    return {
        'schema_version':'jarvis.evidence-summary.v1','runtime_revision':revision,
        'read_only':True,'physical_actuation':False,
        'agents':{'status':'OBSERVED','canonical_agent_count':len(registry['agents']),
            'historical_responsibility_count':sum(len(agent['responsibilities']) for agent in registry['agents']),
            'historical_responsibility_scope':'Migrated responsibility identifiers; not runtime agent identities'},
        'current_stores':{'objectives':objectives,
            'compute_jobs':{**jobs,'status_counts':job_states['counts'] if job_states['status']=='OBSERVED' else None},
            'pwa_sessions':sessions,'artifacts':artifacts,'action_records':actions},
        'legacy_metrics':{
            'agent_count':{'status':'RETIRED_AMBIGUOUS','replacement':'agents.canonical_agent_count'},
            'objectives':{'status':'REPLACED','replacement':'current_stores.objectives.count'},
            'artifacts':{'status':'REPLACED','replacement':'current_stores.artifacts.count'},
            'agent_jobs':{'status':'REPLACED','replacement':'current_stores.compute_jobs.count'},
            'facts':{'status':'NOT_APPLICABLE','reason':'retired app.main store is not the production authority'},
            'memories':{'status':'NOT_APPLICABLE','reason':'retired app.main store is not the production authority'},
            'projects':{'status':'NOT_APPLICABLE','reason':'no equivalent authoritative direct-execution metric'},
            'orchestration_runs':{'status':'NOT_APPLICABLE','reason':'no equivalent authoritative direct-execution metric'}},
        'privacy':{'aggregate_only':True,'record_contents_exposed':False,
            'objective_contents_exposed':False,'artifact_contents_exposed':False,
            'session_credentials_exposed':False}}



def telemetry_store_counts():
    """Only the two stores consumed by telemetry; bound SQLite VM execution."""
    root = Path(os.getenv('PRIME_DATA_DIR', '/data')).resolve()
    objectives = _observed_count(root/'objectives.db', 'SELECT COUNT(*) FROM objectives')
    counts = None
    path = root/'compute-queue.db'
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as db:
                deadline = time.monotonic() + 1
                db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                counts = {str(status): count for status, count in db.execute(
                    "SELECT status,COUNT(*) FROM compute_jobs WHERE status IN ('queued','running','awaiting_approval') GROUP BY status")}
        except (OSError, sqlite3.Error, TypeError, ValueError):
            pass
    return {'objectives': objectives, 'compute_jobs': {'status_counts': counts}}
