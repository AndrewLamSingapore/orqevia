"""Outcome and process metrics in the existing application data domain."""
import json
import sqlite3
import time
import math
from pathlib import Path


class OutcomeMetrics:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reasoning_attempts (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, task_class TEXT NOT NULL, tier TEXT NOT NULL, seconds REAL NOT NULL, tokens INTEGER, cost REAL, verified INTEGER NOT NULL, details TEXT NOT NULL)')
    def connect(self):return sqlite3.connect(self.path,timeout=15)
    def record(self,*,attempt_id,task_id,task_class,tier,seconds,input_tokens=None,output_tokens=None,cost=None,verified=False,**metrics):
        allowed={'agent_id','workflow_id','provider','model','cached_tokens','retrieved_context_bytes','retries','escalations','success','artifact_id','artifact_validation','handoff_accuracy','context_preservation','role_adherence','tool_selection_precision','schema_adherence','repair_cycles','redundant_work','human_interventions','failure_kind','requested_tier','requested_provider','requested_model','fallback_route','error_classifications'}
        if set(metrics)-allowed:raise ValueError('Unrecognized metrics; raw prompts/reasoning are not accepted')
        if not math.isfinite(seconds) or seconds<0:raise ValueError('Invalid duration')
        for value in (input_tokens,output_tokens):
            if value is not None and (type(value) is not int or value<0):raise ValueError('Invalid token count')
        if cost is not None and (not math.isfinite(float(cost)) or float(cost)<0):raise ValueError('Invalid cost')
        if verified and not (metrics.get('artifact_id') and metrics.get('artifact_validation')=='PASS' and metrics.get('success')):raise ValueError('Verified outcome needs actual artifact acceptance')
        tokens=None if input_tokens is None or output_tokens is None else input_tokens+output_tokens
        with self.connect() as c:c.execute('INSERT INTO reasoning_attempts VALUES(?,?,?,?,?,?,?,?,?)',(attempt_id,task_id,task_class,tier,seconds,tokens,None if cost is None else float(cost),int(verified),json.dumps(metrics,sort_keys=True)))
    def summary(self,task_class):
        with self.connect() as c:rows=c.execute('SELECT task_id,seconds,tokens,cost,verified FROM reasoning_attempts WHERE task_class=?',(task_class,)).fetchall()
        verified=len({r[0] for r in rows if r[4]})
        return {'attempts':len(rows),'verified_outcomes':verified,'tokens_per_verified_outcome':sum(r[2] for r in rows)/verified if verified and all(r[2] is not None for r in rows) else None,'cost_per_verified_outcome':sum(r[3] for r in rows)/verified if verified and all(r[3] is not None for r in rows) else None,'seconds_per_verified_outcome':sum(r[1] for r in rows)/verified if verified else None,'missing_usage_attempts':sum(r[2] is None for r in rows),'missing_cost_attempts':sum(r[3] is None for r in rows)}
