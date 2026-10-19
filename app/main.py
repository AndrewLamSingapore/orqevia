import os, re, json, math, sqlite3, difflib, threading, ast, operator
import io, socket, ipaddress, uuid, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from pypdf import PdfReader
from docx import Document as DocxDocument
from .orchestration import SPECIALISTS, choose_specialist, has_consequential_intent, build_task_brief, compact_context, supervisor_status, grounding_guard
from .settings import SETTINGS
from .observability import PRIVACY_FASTAPI_TELEMETRY

OLLAMA=SETTINGS.ollama_base_url
FAST_MODEL=SETTINGS.fast_model
DEEP_MODEL=SETTINGS.deep_model
EMBED_MODEL=SETTINGS.embedding_model
MAX_UPLOAD=int(os.getenv("PRIME_MAX_UPLOAD_MB","25"))*1024*1024
MAX_AGENT_STEPS=max(1,min(10,int(os.getenv("PRIME_MAX_AGENT_STEPS","7"))))
CODE_TIMEOUT=max(2,min(15,int(os.getenv("PRIME_CODE_TIMEOUT_SECONDS","6"))))
DATA=Path(os.getenv("PRIME_DATA_DIR","/data"));DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/"prime.db"; DATASETS=DATA/"datasets"; CODE=DATA/"code_workspace"
DATASETS.mkdir(exist_ok=True);CODE.mkdir(exist_ok=True)
app=FastAPI(docs_url=None,redoc_url=None,telemetry=PRIVACY_FASTAPI_TELEMETRY)
WRITE_LOCK=threading.RLock(); AUTOMATION_STOP=threading.Event(); AUTOMATION_THREAD=None

AGENTS={
"planner":{"name":"Planner Agent","purpose":"Builds controlled execution plans."},
"memory":{"name":"Memory Agent","purpose":"Authoritative personal facts and semantic memory."},
"knowledge":{"name":"Knowledge Agent","purpose":"Retrieves indexed local knowledge."},
"analyst":{"name":"Analyst Agent","purpose":"Deep reasoning, synthesis and strategy."},
"writer":{"name":"Writer Agent","purpose":"Polished user-facing writing."},
"critic":{"name":"Critic Agent","purpose":"Checks drafts for contradictions and weak claims."},
"verifier":{"name":"Verifier Agent","purpose":"Verifies claims against facts and knowledge."},
"research":{"name":"Research Agent","purpose":"Reads and synthesizes explicitly supplied public URLs."},
"data":{"name":"Data Agent","purpose":"Inspects and reasons over local CSV/JSON datasets."},
"coding":{"name":"Coding Agent","purpose":"Generates, validates and safely tests code in a local workspace."},
"actions":{"name":"Actions Agent","purpose":"Queues mutating actions for explicit approval."},
"automation":{"name":"Automation Agent","purpose":"Runs persistent local schedules while ORQEVIA is online."},
"governor":{"name":"Executive Governor","purpose":"Enforces constitution, authority boundaries and institutional policy."},
"executive":{"name":"Executive Orchestrator","purpose":"Turns approved objectives into bounded internal organizational work."},
"portfolio":{"name":"Portfolio Agent","purpose":"Coordinates objectives, projects, dependencies and priorities."},
"auditor":{"name":"Institutional Auditor","purpose":"Records and reviews organizational decisions and governance events."},
"operations":{"name":"Operations Director","purpose":"Maintains persistent queues, schedules and resumable internal work."},
"watchdog":{"name":"Watchdog Agent","purpose":"Detects loops, repeated failures, budget overruns and unsafe autonomous behavior."},
"performance":{"name":"Performance Analyst","purpose":"Measures agent and department success, latency, failures and corrections."},
"dependency":{"name":"Dependency Manager","purpose":"Tracks project/task prerequisites and releases work only when dependencies are satisfied."},
"evaluator":{"name":"Evaluator Agent","purpose":"Scores task artifacts against intent and quality."},
"artifact_curator":{"name":"Artifact Curator","purpose":"Persists internal deliverables with provenance."},
"loop_manager":{"name":"Closed Loop Manager","purpose":"Reviews completed projects and proposes bounded next work."},
"orchestrator":{"name":"ORQEVIA Orchestrator","purpose":"Rewrites queued work into clean self-contained mission briefs and routes it to the right specialist."},
"supervisor":{"name":"Agent Supervisor","purpose":"Monitors bounded jobs, controls retries and stops failed or low-confidence work from silently progressing."},
"compactor":{"name":"Context Compactor","purpose":"Distills verified mission outcomes into durable compact context without carrying raw execution clutter."},
"economic":{"name":"Economic Specialist","purpose":"Connects work to income, cash flow, assets, liabilities, career capital and long-term wealth."},
"communications":{"name":"Communications Specialist","purpose":"Drafts internal communication artifacts only; external sending remains approval-gated."},
"career":{"name":"Career Specialist","purpose":"Turns career objectives into evidence-backed internal positioning, targeting and conversion plans."},

}
BASE_SYSTEM=("You are ORQEVIA V7, a private local multi-agent AI. Use authoritative saved facts. "
"Never invent personal facts. Use only supplied/retrieved evidence for source claims. "
"Never claim an action, research step or code execution that did not actually occur. Be concise, useful and honest.")
ALIASES={"favorite city":["favourite city","preferred city","fav city"],"favorite food":["favourite food","preferred food"],"favorite color":["favourite color","favourite colour","favorite colour"],"goal":["main goal","primary goal"],"project":["current project"],"name":["my name"]}

def now(): return datetime.now(timezone.utc).isoformat()
def connect():
 c=sqlite3.connect(DB,timeout=20,check_same_thread=False);c.row_factory=sqlite3.Row;c.execute("PRAGMA busy_timeout=15000");return c
def table_exists(c,n): return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(n,)).fetchone() is not None
def columns(c,t): return {r['name']:dict(r) for r in c.execute(f"PRAGMA table_info({t})").fetchall()} if table_exists(c,t) else {}
def addcol(c,t,n,ddl):
 if n not in columns(c,t): c.execute(f"ALTER TABLE {t} ADD COLUMN {n} {ddl}")

def ensure_schema(c):
 schemas=[
 "CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT,text TEXT NOT NULL,embedding TEXT,created_at TEXT)",
 "CREATE TABLE IF NOT EXISTS facts(key TEXT PRIMARY KEY,value TEXT NOT NULL,source_text TEXT,updated_at TEXT)",
 "CREATE TABLE IF NOT EXISTS memory_items(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,text TEXT NOT NULL,embedding TEXT,salience REAL DEFAULT .5,created_at TEXT,last_used_at TEXT,use_count INTEGER DEFAULT 0)",
 "CREATE TABLE IF NOT EXISTS structured_facts(id INTEGER PRIMARY KEY AUTOINCREMENT,category TEXT,key TEXT,value TEXT,confidence REAL DEFAULT 1,source_text TEXT,active INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT)",
 "CREATE TABLE IF NOT EXISTS relations(id INTEGER PRIMARY KEY AUTOINCREMENT,subject TEXT,predicate TEXT,object TEXT,confidence REAL DEFAULT 1,active INTEGER DEFAULT 1,created_at TEXT,updated_at TEXT)",
 "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,source_type TEXT NOT NULL,source_ref TEXT,char_count INTEGER DEFAULT 0,chunk_count INTEGER DEFAULT 0,created_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS document_chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,document_id INTEGER NOT NULL,chunk_index INTEGER NOT NULL,text TEXT NOT NULL,embedding TEXT,created_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS agent_runs(id TEXT PRIMARY KEY,user_query TEXT NOT NULL,status TEXT NOT NULL,agents_json TEXT NOT NULL,trace_json TEXT NOT NULL,answer TEXT,error TEXT,created_at TEXT NOT NULL,completed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,title TEXT NOT NULL,status TEXT NOT NULL,query TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL,completed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS research_runs(id TEXT PRIMARY KEY,query TEXT NOT NULL,sources_json TEXT NOT NULL,result TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,name TEXT NOT NULL,stored_name TEXT NOT NULL,kind TEXT NOT NULL,row_count INTEGER,column_count INTEGER,columns_json TEXT,created_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS code_files(id TEXT PRIMARY KEY,name TEXT NOT NULL,language TEXT NOT NULL,path TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS action_queue(id TEXT PRIMARY KEY,action_type TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,resolved_at TEXT,result TEXT)",
 "CREATE TABLE IF NOT EXISTS automations(id TEXT PRIMARY KEY,title TEXT NOT NULL,prompt TEXT NOT NULL,schedule_type TEXT NOT NULL,interval_hours INTEGER,run_at TEXT,next_run_at TEXT,enabled INTEGER DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS automation_runs(id TEXT PRIMARY KEY,automation_id TEXT NOT NULL,status TEXT NOT NULL,result TEXT,error TEXT,started_at TEXT NOT NULL,completed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS org_constitution(id INTEGER PRIMARY KEY AUTOINCREMENT,rule_key TEXT UNIQUE NOT NULL,rule_text TEXT NOT NULL,locked INTEGER DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_objectives(id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER DEFAULT 50,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_departments(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,mission TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_projects(id TEXT PRIMARY KEY,objective_id TEXT,title TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,department TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_project_tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,title TEXT NOT NULL,description TEXT,status TEXT NOT NULL,sequence INTEGER DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS authority_grants(id TEXT PRIMARY KEY,scope TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,expires_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_events(id TEXT PRIMARY KEY,event_type TEXT NOT NULL,actor TEXT NOT NULL,subject TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_portfolios(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER DEFAULT 50,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_portfolio_projects(portfolio_id TEXT NOT NULL,project_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(portfolio_id,project_id))",
 "CREATE TABLE IF NOT EXISTS org_task_dependencies(task_id TEXT NOT NULL,depends_on_task_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(task_id,depends_on_task_id))",
 "CREATE TABLE IF NOT EXISTS org_department_queue(id TEXT PRIMARY KEY,department TEXT NOT NULL,task_id TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER DEFAULT 50,available_at TEXT,lease_until TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_autonomous_runs(id TEXT PRIMARY KEY,status TEXT NOT NULL,objective_id TEXT,portfolio_id TEXT,started_at TEXT NOT NULL,completed_at TEXT,cycles INTEGER DEFAULT 0,tasks_created INTEGER DEFAULT 0,tasks_completed INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,summary TEXT)",
 "CREATE TABLE IF NOT EXISTS org_recurring_jobs(id TEXT PRIMARY KEY,name TEXT NOT NULL,scope TEXT NOT NULL,cadence TEXT NOT NULL,status TEXT NOT NULL,next_run_at TEXT,last_run_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_performance_metrics(id TEXT PRIMARY KEY,entity_type TEXT NOT NULL,entity_name TEXT NOT NULL,metric_name TEXT NOT NULL,metric_value REAL NOT NULL,window TEXT NOT NULL,recorded_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_watchdog_events(id TEXT PRIMARY KEY,severity TEXT NOT NULL,event_type TEXT NOT NULL,subject TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_execution_budget(id TEXT PRIMARY KEY,budget_scope TEXT NOT NULL,budget_key TEXT NOT NULL,limit_value REAL NOT NULL,used_value REAL DEFAULT 0,window_start TEXT NOT NULL,window_end TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_artifacts(id TEXT PRIMARY KEY,task_id TEXT,project_id TEXT,run_id TEXT,title TEXT NOT NULL,artifact_type TEXT NOT NULL,content TEXT NOT NULL,verification_status TEXT NOT NULL,quality_score REAL DEFAULT 0,verifier_feedback TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_project_reviews(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,objective_id TEXT,score REAL DEFAULT 0,summary TEXT NOT NULL,next_tasks_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
 "CREATE TABLE IF NOT EXISTS org_approval_requests(id TEXT PRIMARY KEY,request_type TEXT NOT NULL,subject_id TEXT,title TEXT NOT NULL,details_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,resolved_at TEXT)",
 "CREATE TABLE IF NOT EXISTS org_orchestration_runs(id TEXT PRIMARY KEY,objective_id TEXT,status TEXT NOT NULL,started_at TEXT NOT NULL,completed_at TEXT,missions_planned INTEGER DEFAULT 0,jobs_completed INTEGER DEFAULT 0,jobs_retried INTEGER DEFAULT 0,failures INTEGER DEFAULT 0,summary TEXT)",
 "CREATE TABLE IF NOT EXISTS org_agent_jobs(id TEXT PRIMARY KEY,orchestration_run_id TEXT NOT NULL,task_id TEXT,project_id TEXT,objective_id TEXT,specialist TEXT NOT NULL,status TEXT NOT NULL,brief TEXT NOT NULL,attempts INTEGER DEFAULT 0,max_attempts INTEGER DEFAULT 2,last_status TEXT,result TEXT,artifact_id TEXT,started_at TEXT NOT NULL,updated_at TEXT NOT NULL,completed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS org_agent_inbox(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,orchestration_run_id TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,consumed_at TEXT)",
 "CREATE TABLE IF NOT EXISTS org_context_summaries(id TEXT PRIMARY KEY,scope_type TEXT NOT NULL,scope_id TEXT NOT NULL,summary TEXT NOT NULL,source_count INTEGER DEFAULT 1,created_at TEXT NOT NULL)",

 ]
 for s in schemas:c.execute(s)
 legacy={"memories":{"embedding":"TEXT","created_at":"TEXT"},"facts":{"source_text":"TEXT","updated_at":"TEXT"},"memory_items":{"kind":"TEXT","embedding":"TEXT","salience":"REAL DEFAULT .5","created_at":"TEXT","last_used_at":"TEXT","use_count":"INTEGER DEFAULT 0"},"structured_facts":{"category":"TEXT","confidence":"REAL DEFAULT 1","source_text":"TEXT","active":"INTEGER DEFAULT 1","created_at":"TEXT","updated_at":"TEXT"},"relations":{"confidence":"REAL DEFAULT 1","active":"INTEGER DEFAULT 1","created_at":"TEXT","updated_at":"TEXT"}}
 for t,defs in legacy.items():
  if table_exists(c,t):
   for col,ddl in defs.items():addcol(c,t,col,ddl)
 ts=now()
 for t,col in [("memories","created_at"),("facts","updated_at"),("memory_items","created_at"),("structured_facts","created_at"),("structured_facts","updated_at"),("relations","created_at"),("relations","updated_at")]:
  if table_exists(c,t) and col in columns(c,t):c.execute(f"UPDATE {t} SET {col}=? WHERE {col} IS NULL OR {col}=''",(ts,))
 c.execute("UPDATE structured_facts SET active=1 WHERE active IS NULL");c.execute("UPDATE relations SET active=1 WHERE active IS NULL")
 for sql in ["CREATE INDEX IF NOT EXISTS idx_sf ON structured_facts(active,key)","CREATE INDEX IF NOT EXISTS idx_mem ON memory_items(id)","CREATE INDEX IF NOT EXISTS idx_doc ON document_chunks(document_id,chunk_index)","CREATE INDEX IF NOT EXISTS idx_action_status ON action_queue(status,created_at)","CREATE INDEX IF NOT EXISTS idx_auto_next ON automations(enabled,next_run_at)","CREATE INDEX IF NOT EXISTS idx_orch_runs ON org_orchestration_runs(started_at,status)","CREATE INDEX IF NOT EXISTS idx_agent_jobs_run ON org_agent_jobs(orchestration_run_id,status)","CREATE INDEX IF NOT EXISTS idx_agent_inbox_run ON org_agent_inbox(orchestration_run_id,status)","CREATE INDEX IF NOT EXISTS idx_context_scope ON org_context_summaries(scope_type,scope_id,created_at)"]:c.execute(sql)

def migrate(c):
 if not c.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
  if table_exists(c,'facts') and {'key','value'}<=set(columns(c,'facts')):
   for r in c.execute("SELECT key,value,source_text,updated_at FROM facts").fetchall():
    if r['key'] and r['value'] and not c.execute("SELECT 1 FROM structured_facts WHERE key=? AND active=1",(r['key'],)).fetchone():
     ts=r['updated_at'] or now();c.execute("INSERT INTO structured_facts(category,key,value,confidence,source_text,active,created_at,updated_at) VALUES('fact',?,?,1,?,1,?,?)",(r['key'],r['value'],r['source_text'],ts,ts))
  c.execute("INSERT INTO schema_migrations VALUES(1,?)",(now(),))
 if not c.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
  if table_exists(c,'memories') and 'text' in columns(c,'memories'):
   for r in c.execute("SELECT text,embedding,created_at FROM memories").fetchall():
    if r['text'] and not c.execute("SELECT 1 FROM memory_items WHERE text=?",(r['text'],)).fetchone():c.execute("INSERT INTO memory_items(kind,text,embedding,salience,created_at,use_count) VALUES('legacy',?,?,.55,?,0)",(r['text'],r['embedding'],r['created_at'] or now()))
  c.execute("INSERT INTO schema_migrations VALUES(2,?)",(now(),))

def init_db():
 with WRITE_LOCK:
  c=connect()
  try:c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA synchronous=NORMAL");ensure_schema(c);migrate(c);c.commit()
  finally:c.close()


CONSTITUTION_RULES={
"authority_boundary":"Capability may expand, but authority may not expand without explicit user approval.",
"personal_fact_integrity":"Personal facts must come from authoritative saved memory. Unknown personal facts must not be guessed.",
"external_action_gate":"Consequential external actions require explicit approval unless covered by a narrow active authority grant.",
"core_policy_lock":"Agents may not silently rewrite or disable core governance or security policy.",
"financial_gate":"Purchases, payments, financial transactions and account permission changes require explicit user approval.",
"destructive_gate":"Destructive file operations and irreversible actions require explicit user approval.",
"publishing_gate":"External publishing and outbound communications require explicit user approval in Phase 1.",
"auditability":"Material organizational decisions and autonomous cycles must be recorded in the institutional event ledger.",
"bounded_execution":"Autonomous cycles must remain bounded by configured execution, time and resource limits."
}
DEFAULT_DEPARTMENTS=[("Strategy","Translate objectives into priorities and internal plans."),("Research","Develop evidence and knowledge for organizational decisions."),("Data","Analyze local datasets and measurable evidence."),("Engineering","Design, code, test and maintain approved internal artifacts."),("Knowledge","Maintain indexed documents, institutional memory and retrieval."),("Quality","Critique, verify and audit organizational outputs.")]
def org_event(event_type,actor,subject=None,details=None):
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_events(id,event_type,actor,subject,details_json,created_at) VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),event_type,actor,subject,json.dumps(details or {}),now()));c.commit()
  finally:c.close()
def seed_governance():
 with WRITE_LOCK:
  c=connect()
  try:
   ts=now()
   for k,v in CONSTITUTION_RULES.items():c.execute("INSERT INTO org_constitution(rule_key,rule_text,locked,created_at,updated_at) VALUES(?,?,1,?,?) ON CONFLICT(rule_key) DO NOTHING",(k,v,ts,ts))
   for name,mission in DEFAULT_DEPARTMENTS:c.execute("INSERT INTO org_departments(id,name,mission,status,created_at,updated_at) VALUES(?,?,?,'active',?,?) ON CONFLICT(name) DO NOTHING",(str(uuid.uuid4()),name,mission,ts,ts))
   c.commit()
  finally:c.close()
def governance_counts():
 c=connect()
 try:return {"objectives":c.execute("SELECT COUNT(*) FROM org_objectives WHERE status='active'").fetchone()[0],"projects":c.execute("SELECT COUNT(*) FROM org_projects WHERE status IN ('draft','active')").fetchone()[0],"project_tasks":c.execute("SELECT COUNT(*) FROM org_project_tasks WHERE status IN ('planned','active')").fetchone()[0],"departments":c.execute("SELECT COUNT(*) FROM org_departments WHERE status='active'").fetchone()[0],"authority_grants":c.execute("SELECT COUNT(*) FROM authority_grants WHERE status='active'").fetchone()[0]}
 finally:c.close()


PHASE2_MAX_TASKS=int(os.environ.get("PRIME_AUTONOMOUS_CYCLE_MAX_TASKS","8"))
PHASE2_MAX_PROJECTS=int(os.environ.get("PRIME_AUTONOMOUS_CYCLE_MAX_PROJECTS","3"))
PHASE2_DAILY_BUDGET=float(os.environ.get("PRIME_AUTONOMOUS_DAILY_BUDGET","24"))
WATCHDOG_MAX_FAILURES=int(os.environ.get("PRIME_WATCHDOG_MAX_CONSECUTIVE_FAILURES","3"))
WATCHDOG_MAX_CYCLES_HOURLY=int(os.environ.get("PRIME_WATCHDOG_MAX_CYCLES_PER_HOUR","4"))

def watchdog_event(severity,event_type,subject=None,details=None):
 with WRITE_LOCK:
  c=connect()
  try:
   c.execute("INSERT INTO org_watchdog_events(id,severity,event_type,subject,details_json,created_at) VALUES(?,?,?,?,?,?)",
             (str(uuid.uuid4()),severity,event_type,subject,json.dumps(details or {}),now()));c.commit()
  finally:c.close()

def phase2_counts():
 c=connect()
 try:
  return {
   "portfolios":c.execute("SELECT COUNT(*) FROM org_portfolios WHERE status='active'").fetchone()[0],
   "queued_tasks":c.execute("SELECT COUNT(*) FROM org_department_queue WHERE status='queued'").fetchone()[0],
   "autonomous_runs":c.execute("SELECT COUNT(*) FROM org_autonomous_runs").fetchone()[0],
   "recurring_jobs":c.execute("SELECT COUNT(*) FROM org_recurring_jobs WHERE status='active'").fetchone()[0],
   "watchdog_events":c.execute("SELECT COUNT(*) FROM org_watchdog_events").fetchone()[0],
  }
 finally:c.close()

PHASE3_VERIFY_THRESHOLD=float(os.environ.get("PRIME_PHASE3_VERIFY_THRESHOLD","65"))
PHASE3_MAX_REVISIONS=int(os.environ.get("PRIME_PHASE3_MAX_REVISIONS","1"))
PHASE3_MAX_TASKS_PER_RUN=int(os.environ.get("PRIME_PHASE3_MAX_TASKS_PER_RUN","3"))
ORCH_MAX_JOBS=max(1,min(5,int(os.environ.get("PRIME_ORCHESTRATION_MAX_JOBS","3"))))
ORCH_MAX_ATTEMPTS=max(1,min(3,int(os.environ.get("PRIME_ORCHESTRATION_MAX_ATTEMPTS","2"))))

def phase3_counts():
 c=connect()
 try:return {"artifacts":c.execute("SELECT COUNT(*) FROM org_artifacts").fetchone()[0],"verified_artifacts":c.execute("SELECT COUNT(*) FROM org_artifacts WHERE verification_status='verified'").fetchone()[0],"project_reviews":c.execute("SELECT COUNT(*) FROM org_project_reviews").fetchone()[0],"pending_approvals":c.execute("SELECT COUNT(*) FROM org_approval_requests WHERE status='pending'").fetchone()[0]}
 finally:c.close()

def orchestration_counts():
 c=connect()
 try:return {
  "orchestration_runs":c.execute("SELECT COUNT(*) FROM org_orchestration_runs").fetchone()[0],
  "agent_jobs":c.execute("SELECT COUNT(*) FROM org_agent_jobs").fetchone()[0],
  "running_agent_jobs":c.execute("SELECT COUNT(*) FROM org_agent_jobs WHERE status='running'").fetchone()[0],
  "agent_inbox":c.execute("SELECT COUNT(*) FROM org_agent_inbox WHERE status='unread'").fetchone()[0],
  "context_summaries":c.execute("SELECT COUNT(*) FROM org_context_summaries").fetchone()[0],
 }
 finally:c.close()

def create_artifact(task_id,project_id,run_id,title,content,status="pending",score=0,feedback=""):
 aid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_artifacts(id,task_id,project_id,run_id,title,artifact_type,content,verification_status,quality_score,verifier_feedback,created_at,updated_at) VALUES(?,?,?,?,?,'internal_deliverable',?,?,?,?,?,?)",(aid,task_id,project_id,run_id,title,content,status,float(score),feedback,ts,ts));c.commit()
  finally:c.close()
 return aid

def update_artifact(aid,content,status,score,feedback):
 with WRITE_LOCK:
  c=connect()
  try:c.execute("UPDATE org_artifacts SET content=?,verification_status=?,quality_score=?,verifier_feedback=?,updated_at=? WHERE id=?",(content,status,float(score),feedback,now(),aid));c.commit()
  finally:c.close()

def approval_request(request_type,subject_id,title,details):
 rid=str(uuid.uuid4())
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_approval_requests(id,request_type,subject_id,title,details_json,status,created_at,resolved_at) VALUES(?,?,?,?,?,'pending',?,NULL)",(rid,request_type,subject_id,title,json.dumps(details),now()));c.commit()
  finally:c.close()
 org_event('approval_requested','phase3',rid,{'type':request_type,'subject':subject_id});return rid

async def phase3_verify(task_title,task_description,content,*,specialist="strategy",evidence_context=""):
 guard_ok,guard_feedback=grounding_guard(content,specialist,evidence_context)
 if not guard_ok:
  return 0,"revise","GROUNDING FAIL: "+guard_feedback,"deterministic_grounding_guard"

 evidence_label=evidence_context[:12000] if evidence_context else "NO VERIFIED EXTERNAL/DATA EVIDENCE ATTACHED."
 prompt=f"""You are ORQEVIA Phase 3.1.1 Evidence-Grounded Evaluator.
TASK: {task_title}
DESCRIPTION: {task_description}
SPECIALIST: {specialist}

VERIFIED EVIDENCE AVAILABLE:
{evidence_label}

DELIVERABLE:
{content[:16000]}

Return STRICT JSON only:
{{"score":0-100,"verdict":"pass" or "revise","feedback":"concise feedback"}}

NON-NEGOTIABLE GROUNDING RULES:
- A polished answer with unsupported facts MUST fail.
- Any claimed database, log, dataset, user count, transaction, amount, percentage, timestamp, location, behavioral observation, external research result, or tool result must be traceable to VERIFIED EVIDENCE AVAILABLE.
- If evidence is insufficient, the correct deliverable is EVIDENCE_REQUIRED or DATA_REQUIRED, not invented analysis.
- For Data specialist work, require an exact SOURCE DATASET name and ID.
- Uncertainty wording does not excuse fabricated evidence.
- Score unsupported empirical claims at 20 or below and verdict revise.
- Otherwise score relevance, completeness, consistency, usefulness, provenance and evidence fidelity."""
 try:
  d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
  o=_extract_json_object(d['message']['content'].strip())
  score=max(0,min(100,float(o.get("score",0)))) if isinstance(o,dict) else 0
  verdict=str(o.get("verdict","revise")).lower() if isinstance(o,dict) else "revise"
  feedback=str(o.get("feedback","")).strip()[:4000] if isinstance(o,dict) else "Malformed evaluator output."
  if verdict not in {"pass","revise"}:verdict="revise"
  # Deterministic guard remains authoritative even if evaluator model is permissive.
  return score,verdict,feedback,"model+grounding_guard"
 except Exception as e:
  # Fallback is intentionally conservative: structure alone cannot establish factual grounding.
  n=len((content or "").strip())
  score=65 if n>=180 else (45 if n>=80 else 20)
  verdict="pass" if score>=PHASE3_VERIFY_THRESHOLD and guard_ok else "revise"
  return score,verdict,"Conservative deterministic evaluator fallback; grounding guard passed. "+str(e)[:300],"deterministic_fallback+grounding_guard"

async def phase3_review_project(project_id):
 c=connect()
 try:
  p=c.execute("SELECT * FROM org_projects WHERE id=?",(project_id,)).fetchone()
  if not p:return None
  old=c.execute("SELECT id FROM org_project_reviews WHERE project_id=? ORDER BY created_at DESC LIMIT 1",(project_id,)).fetchone()
  if old:return old['id']
  tasks=[dict(r) for r in c.execute("SELECT * FROM org_project_tasks WHERE project_id=? ORDER BY sequence",(project_id,))]
  arts=[dict(r) for r in c.execute("SELECT * FROM org_artifacts WHERE project_id=? AND verification_status='verified' ORDER BY created_at",(project_id,))]
 finally:c.close()
 if not tasks or any(t["status"]!="completed" for t in tasks):return None
 packet="\n\n".join([f"TASK: {t['title']}\nARTIFACT: "+next((a["content"] for a in arts if a["task_id"]==t["id"]),"No artifact")[:4500] for t in tasks])
 prompt=f"""You are ORQEVIA Phase 3 Closed Loop Manager.
PROJECT: {p['title']}
DESCRIPTION: {p['description']}
COMPLETED WORK:
{packet[:22000]}
Return STRICT JSON only:
{{"score":0-100,"summary":"achievement and gaps","next_tasks":[{{"title":"...","description":"..."}}]}}
Rules: 0-3 next_tasks; internal work only; no purchases, payments, external messages, publishing, account changes or destructive actions."""
 try:
  d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
  o=_extract_json_object(d['message']['content'].strip()) or {}
 except Exception:o={}
 score=max(0,min(100,float(o.get("score",75) or 75)));summary=str(o.get("summary","Completed project reviewed; next work requires approval."))[:10000]
 nts=o.get("next_tasks",[]) if isinstance(o.get("next_tasks",[]),list) else [];clean=[]
 for t in nts[:3]:
  if isinstance(t,dict) and str(t.get("title","")).strip():clean.append({"title":str(t.get("title","")).strip()[:300],"description":str(t.get("description","")).strip()[:5000]})
 rid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_project_reviews(id,project_id,objective_id,score,summary,next_tasks_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,'reviewed',?,?)",(rid,project_id,p['objective_id'],score,summary,json.dumps(clean),ts,ts));c.commit()
  finally:c.close()
 if clean:approval_request("followup_tasks",rid,"Approve Phase 3 follow-up tasks",{"project_id":project_id,"tasks":clean})
 org_event('phase3_project_reviewed','loop_manager',project_id,{'review_id':rid,'score':score,'next_tasks':len(clean)});return rid

def seed_phase2():
 with WRITE_LOCK:
  c=connect()
  try:
   ts=now()
   # Daily autonomous budget.
   c.execute("""INSERT INTO org_execution_budget(id,budget_scope,budget_key,limit_value,used_value,window_start,window_end,updated_at)
                SELECT ?, 'autonomy','daily_cycles',?,0,?,?,?
                WHERE NOT EXISTS(SELECT 1 FROM org_execution_budget WHERE budget_scope='autonomy' AND budget_key='daily_cycles')""",
             (str(uuid.uuid4()),PHASE2_DAILY_BUDGET,ts,ts,ts))
   c.commit()
  finally:c.close()

def queue_task(task_id,department,priority=50,available_at=None):
 with WRITE_LOCK:
  c=connect()
  try:
   exists=c.execute("SELECT 1 FROM org_department_queue WHERE task_id=? AND status IN ('queued','leased') LIMIT 1",(task_id,)).fetchone()
   if not exists:
    ts=now()
    c.execute("""INSERT INTO org_department_queue(id,department,task_id,status,priority,available_at,lease_until,created_at,updated_at)
                 VALUES(?,?,?,'queued',?,?,NULL,?,?)""",
              (str(uuid.uuid4()),department,task_id,max(1,min(100,int(priority))),available_at,ts,ts))
    c.commit()
  finally:c.close()

def dependencies_satisfied(task_id):
 c=connect()
 try:
  deps=[r[0] for r in c.execute("SELECT depends_on_task_id FROM org_task_dependencies WHERE task_id=?",(task_id,))]
  for dep in deps:
   row=c.execute("SELECT status FROM org_project_tasks WHERE id=?",(dep,)).fetchone()
   if not row or row[0]!="completed":return False
  return True
 finally:c.close()

def record_metric(entity_type,entity_name,metric_name,value,window="lifetime"):
 with WRITE_LOCK:
  c=connect()
  try:
   c.execute("INSERT INTO org_performance_metrics(id,entity_type,entity_name,metric_name,metric_value,window,recorded_at) VALUES(?,?,?,?,?,?,?)",
             (str(uuid.uuid4()),entity_type,entity_name,metric_name,float(value),window,now()));c.commit()
  finally:c.close()

def watchdog_can_run():
 c=connect()
 try:
  recent=c.execute("SELECT COUNT(*) FROM org_autonomous_runs WHERE started_at>=datetime('now','-1 hour')").fetchone()[0]
  if recent>=WATCHDOG_MAX_CYCLES_HOURLY:
   return False,"hourly cycle limit reached"
  failures=c.execute("SELECT failures FROM org_autonomous_runs ORDER BY started_at DESC LIMIT ?",(WATCHDOG_MAX_FAILURES,)).fetchall()
  if len(failures)>=WATCHDOG_MAX_FAILURES and all(int(r[0] or 0)>0 for r in failures):
   return False,"consecutive failure threshold reached"
  return True,"ok"
 finally:c.close()

def select_next_queue_item():
 c=connect()
 try:
  rows=c.execute("""SELECT q.id,q.task_id,q.department,q.priority,t.title,t.description,t.project_id
                    FROM org_department_queue q JOIN org_project_tasks t ON t.id=q.task_id
                    WHERE q.status='queued'
                    ORDER BY q.priority DESC,q.created_at ASC LIMIT 50""").fetchall()
 finally:c.close()
 for r in rows:
  if dependencies_satisfied(r["task_id"]):
   return dict(r)
 return None


async def ollama_post(path,payload,timeout=900):
 async with httpx.AsyncClient(timeout=timeout) as h:
  r=await h.post(OLLAMA+path,json=payload);r.raise_for_status();return r.json()
async def embed_one(t):return (await ollama_post('/api/embed',{'model':EMBED_MODEL,'input':t},180))['embeddings'][0]
async def embed_many(ts):return (await ollama_post('/api/embed',{'model':EMBED_MODEL,'input':ts},600))['embeddings'] if ts else []
def cosine(a,b):
 if not a or not b or len(a)!=len(b):return -1
 x=math.sqrt(sum(v*v for v in a));y=math.sqrt(sum(v*v for v in b));return sum(i*j for i,j in zip(a,b))/(x*y) if x and y else -1
def norm(s):return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9 ]+',' ',str(s).lower().replace('favourite','favorite'))).strip()
def canon(s):
 n=norm(s)
 for k,vs in ALIASES.items():
  if n in {norm(k),*(norm(x) for x in vs)}:return k
 return re.sub(r'^(my|the|your)\s+','',n)
def extract_fact(text):
 t=text.strip().rstrip('.!?')
 for p in [r'(?i)^(?:please\s+)?remember(?:\s+that)?\s+my\s+(.+?)\s+is\s+(.+)$',r'(?i)^my\s+(.+?)\s+is\s+(.+?)(?:\s*[,.]?\s*remember\s+this)?$',r'(?i)^remember\s+my\s+(.+?)\s+is\s+(.+)$']:
  m=re.match(p,t)
  if m:
   k,v=canon(m.group(1)),m.group(2).strip().rstrip('.!?');return (k,v,'preference' if 'favorite' in k else 'fact') if k and v else None
 return None
def recall_key(text):
 t=norm(text)
 for pre in ['do you know ','do you remember ','can you remember ','remind me of ','tell me ','please tell me ']:
  if t.startswith(pre):t=t[len(pre):]
 m=re.match(r'(?:what is|whats) my (.+)$',t)
 if m:return canon(m.group(1))
 for k,vs in ALIASES.items():
  if any(x in t for x in {norm(k),*(norm(v) for v in vs)}):return k
 return None
def best_fact(k):
 c=connect();rows=c.execute("SELECT * FROM structured_facts WHERE active=1").fetchall();c.close();k=canon(k)
 for r in rows:
  if canon(r['key'])==k:return dict(r)
 return None
def save_fact(k,v,cat,src):
 k=canon(k);ts=now()
 with WRITE_LOCK:
  c=connect();old=c.execute("SELECT * FROM structured_facts WHERE key=? AND active=1 ORDER BY id DESC LIMIT 1",(k,)).fetchone()
  if old and norm(old['value'])!=norm(v):c.execute("UPDATE structured_facts SET active=0,updated_at=? WHERE id=?",(ts,old['id']));old=None
  if old:c.execute("UPDATE structured_facts SET value=?,source_text=?,updated_at=? WHERE id=?",(v,src,ts,old['id']))
  else:c.execute("INSERT INTO structured_facts(category,key,value,confidence,source_text,active,created_at,updated_at) VALUES(?,?,?,1,?,1,?,?)",(cat,k,v,src,ts,ts))
  c.execute("INSERT INTO facts(key,value,source_text,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,source_text=excluded.source_text,updated_at=excluded.updated_at",(k,v,src,ts));c.commit();c.close()
def save_memory(text,kind='conversation',vec=None):
 p=json.dumps(vec) if vec else None
 with WRITE_LOCK:
  c=connect();c.execute("INSERT INTO memory_items(kind,text,embedding,salience,created_at,use_count) VALUES(?,?,?,.5,?,0)",(kind,text,p,now()));c.execute("INSERT INTO memories(text,embedding,created_at) VALUES(?,?,?)",(text,p,now()));c.commit();c.close()
def allfacts():
 c=connect();rows=[dict(r) for r in c.execute("SELECT category,key,value FROM structured_facts WHERE active=1 ORDER BY updated_at DESC LIMIT 80")];c.close();return rows
def recent(n=8):
 c=connect();rows=[r['text'] for r in c.execute("SELECT text FROM memory_items ORDER BY id DESC LIMIT ?",(n,))];c.close();return list(reversed(rows))
async def semantic_memory(q,n=5):
 try:qv=await embed_one(q)
 except:return []
 c=connect();rows=c.execute("SELECT text,embedding FROM memory_items WHERE embedding IS NOT NULL ORDER BY id DESC LIMIT 500").fetchall();c.close();sc=[]
 for r in rows:
  try:sc.append((cosine(qv,json.loads(r['embedding'])),r['text']))
  except:pass
 return [t for s,t in sorted(sc,reverse=True)[:n] if s>=.18]

def chunk_text(text,size=1000,overlap=150):
 text=re.sub(r'\r\n?','\n',text).strip();out=[];i=0
 while i<len(text):
  e=min(len(text),i+size);piece=text[i:e].strip()
  if piece:out.append(piece)
  if e>=len(text):break
  i=max(i+1,e-overlap)
 return out
async def index_document(name,stype,sref,text):
 chunks=chunk_text(text)
 if not chunks:raise HTTPException(400,'No readable text found.')
 vecs=[]
 for i in range(0,len(chunks),16):vecs.extend(await embed_many(chunks[i:i+16]))
 with WRITE_LOCK:
  c=connect();cur=c.execute("INSERT INTO documents(name,source_type,source_ref,char_count,chunk_count,created_at) VALUES(?,?,?,?,?,?)",(name,stype,sref,len(text),len(chunks),now()));did=cur.lastrowid
  for j,(ch,v) in enumerate(zip(chunks,vecs)):c.execute("INSERT INTO document_chunks(document_id,chunk_index,text,embedding,created_at) VALUES(?,?,?,?,?)",(did,j,ch,json.dumps(v),now()))
  c.commit();c.close()
 return {'id':did,'name':name,'chunks':len(chunks)}
async def document_context(q,n=6):
 c=connect();rows=c.execute("SELECT dc.text,dc.embedding,d.name FROM document_chunks dc JOIN documents d ON d.id=dc.document_id WHERE dc.embedding IS NOT NULL ORDER BY dc.id DESC LIMIT 2000").fetchall();c.close()
 if not rows:return []
 try:qv=await embed_one(q)
 except:return []
 sc=[]
 for r in rows:
  try:sc.append((cosine(qv,json.loads(r['embedding'])),r['name'],r['text']))
  except:pass
 return [{'name':a,'text':b} for s,a,b in sorted(sc,reverse=True)[:n] if s>=.15]
def parse_upload(name,data):
 ext=Path(name).suffix.lower()
 if ext in {'.txt','.md','.csv','.json'}:return data.decode('utf-8',errors='replace')
 if ext=='.pdf':return '\n\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages)
 if ext=='.docx':return '\n'.join(p.text for p in DocxDocument(io.BytesIO(data)).paragraphs)
 raise HTTPException(400,'Supported: TXT, MD, CSV, JSON, PDF, DOCX.')
class TextExtractor(HTMLParser):
 def __init__(self):super().__init__();self.parts=[];self.skip=0
 def handle_starttag(self,t,a):
  if t in {'script','style','noscript'}:self.skip+=1
 def handle_endtag(self,t):
  if t in {'script','style','noscript'} and self.skip:self.skip-=1
 def handle_data(self,d):
  if not self.skip and d.strip():self.parts.append(d.strip())
def public_url(url):
 p=urlparse(url)
 if p.scheme not in {'http','https'} or not p.hostname:raise HTTPException(400,'Use a public http/https URL.')
 try:infos=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
 except:raise HTTPException(400,'Hostname could not be resolved.')
 for info in infos:
  ip=ipaddress.ip_address(info[4][0])
  if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:raise HTTPException(400,'Private/local network URLs are blocked.')
 return url
async def fetch_page(url):
 url=public_url(url)
 async with httpx.AsyncClient(timeout=20,follow_redirects=True,headers={'User-Agent':'PRIME-V7.3.1/1.0'}) as h:
  r=await h.get(url);r.raise_for_status();public_url(str(r.url))
  if len(r.content)>2_000_000:raise HTTPException(413,'Page too large.')
  if 'html' not in r.headers.get('content-type','') and 'text' not in r.headers.get('content-type',''):raise HTTPException(400,'URL is not readable HTML/text.')
  x=TextExtractor();x.feed(r.text);text='\n'.join(x.parts)
  return {'url':str(r.url),'title':urlparse(str(r.url)).hostname or str(r.url),'text':text[:60000]}
def choose_model(q):
 n=norm(q);return (DEEP_MODEL,'deep') if len(q)>650 or any(x in n for x in ['analyze','compare','strategy','plan','evaluate','design','architecture','research','code','data']) else (FAST_MODEL,'fast')
async def llm(system,user,model=None):
 model=model or choose_model(user)[0];d=await ollama_post('/api/chat',{'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'stream':False},900);return d['message']['content'].strip(),model

def counts():
 c=connect();out={}
 for k,t,whr in [('facts','structured_facts',' WHERE active=1'),('memories','memory_items',''),('documents','documents',''),('datasets','datasets',''),('code_files','code_files',''),('pending_actions','action_queue'," WHERE status='pending'"),('automations','automations',' WHERE enabled=1')]:out[k]=c.execute(f'SELECT COUNT(*) FROM {t}{whr}').fetchone()[0]
 c.close();return out

def make_run(q,agents):
 rid=str(uuid.uuid4());tid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect();c.execute("INSERT INTO agent_runs(id,user_query,status,agents_json,trace_json,created_at) VALUES(?,?,?,?,?,?)",(rid,q,'running',json.dumps(agents),json.dumps([]),ts));c.execute("INSERT INTO tasks(id,title,status,query,created_at) VALUES(?,?,?,?,?)",(tid,q[:70],'running',q,ts));c.commit();c.close()
 return rid,tid
def finish_run(rid,tid,status,trace,ans=None,err=None):
 with WRITE_LOCK:
  c=connect();c.execute("UPDATE agent_runs SET status=?,trace_json=?,answer=?,error=?,completed_at=? WHERE id=?",(status,json.dumps(trace),ans,err,now(),rid));c.execute("UPDATE tasks SET status=?,result=?,completed_at=? WHERE id=?",(status,ans or err,now(),tid));c.commit();c.close()

async def orchestrate(q,remember=True,automation=False):
 fact=extract_fact(q)
 if remember and fact:save_fact(*fact,q)
 rk=recall_key(q)
 if rk:
  hit=best_fact(rk)
  if hit:return {'answer':f"Your {hit['key']} is {hit['value']}.",'agents':['memory'],'route':'memory','model':None}
  return {'answer':"I don't know that personal fact yet. Tell me explicitly and say “Remember this.”",'agents':['memory'],'route':'memory_guard','model':None}
 facts=allfacts();mem=recent()+await semantic_memory(q);docs=await document_context(q)
 context=[]
 if facts:context.append('AUTHORITATIVE FACTS:\n'+'\n'.join(f"- {x['key']}: {x['value']}" for x in facts))
 if mem:context.append('RELEVANT MEMORY:\n'+'\n\n'.join(mem[-10:]))
 if docs:context.append('LOCAL KNOWLEDGE:\n'+'\n\n'.join(f"[{d['name']}]\n{d['text']}" for d in docs))
 ctx='\n\n'.join(context) or 'No relevant saved context.'
 n=norm(q);agents=['memory'];
 if docs:agents.append('knowledge')
 if any(x in n for x in ['research','source','web page']):agents.append('research')
 if any(x in n for x in ['data','csv','dataset','statistics']):agents.append('data')
 if any(x in n for x in ['code','python','program','script','debug']):agents.append('coding')
 agents+=['planner','analyst','critic','verifier'] if len(q)>350 or any(x in n for x in ['analyze','compare','strategy','plan','evaluate','design','why']) else ['analyst']
 agents=list(dict.fromkeys(agents))[:MAX_AGENT_STEPS]
 rid,tid=make_run(q,agents);trace=[]
 try:
  import asyncio
  from .runtime import orchestrator as canonical_orchestrator
  outcome=await asyncio.to_thread(canonical_orchestrator.execute,intent=q,department=choose_specialist('',q,ctx).specialist,context=ctx,allow_frontier=False,deep=choose_model(q)[1]=='deep')
  released=outcome.get('result')
  if released:
   draft=released['text'];model=released['model'];trace.append({'agent':'canonical_orchestrator','status':'released','task_id':released['task_id'],'evaluation':outcome['evaluation']})
  else:
   hold=outcome['confidence_hold'];draft="I’m holding this answer because it did not pass the post-generation confidence gate. " + hold['reason'] + (" Evidence gaps: " + "; ".join(hold.get('evidence_gaps') or []) if hold.get('evidence_gaps') else '')
   model=outcome['withheld_result']['model'];trace.append({'agent':'canonical_orchestrator','status':'confidence_hold','task_id':outcome['withheld_result']['task_id'],'evaluation':outcome['evaluation']})
  agents=list(dict.fromkeys(['memory','canonical_orchestrator','evaluator']+(['confidence_gate'] if not released else [])))
  if remember and not automation:
   try:v=await embed_one(q)
   except:v=None
   save_memory(f'User: {q}\nORQEVIA: {draft}','conversation',v)
  finish_run(rid,tid,'completed',trace,draft)
  return {'answer':draft,'agents':agents,'route':'orchestrated','model':model,'run_id':rid}
 except Exception as e:
  finish_run(rid,tid,'failed',trace,err=str(e));raise

SAFE_IMPORTS={'math','statistics','json','re','csv','datetime','collections','itertools','functools','decimal','fractions'}
BLOCKED_CALLS={'eval','exec','compile','__import__','open','input','breakpoint','getattr','setattr','delattr','vars','dir','globals','locals'}
def validate_python(code):
 try:tree=ast.parse(code)
 except SyntaxError as e:return False,f'SyntaxError line {e.lineno}: {e.msg}'
 for n in ast.walk(tree):
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   names=[a.name.split('.')[0] for a in n.names] if isinstance(n,ast.Import) else [(n.module or '').split('.')[0]]
   if any(x not in SAFE_IMPORTS for x in names):return False,'Blocked import. Allowed: '+', '.join(sorted(SAFE_IMPORTS))
  if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in BLOCKED_CALLS:return False,f'Blocked call: {n.func.id}'
  if isinstance(n,ast.Attribute) and n.attr.startswith('__'):return False,'Dunder attribute access is blocked.'
 return True,'Valid restricted Python.'
def run_python(code):
 ok,msg=validate_python(code)
 if not ok:raise HTTPException(400,msg)
 try:
  r=subprocess.run([sys.executable,'-I','-c',code],cwd=str(CODE),capture_output=True,text=True,timeout=CODE_TIMEOUT,env={'PYTHONIOENCODING':'utf-8'})
  return {'returncode':r.returncode,'stdout':r.stdout[-12000:],'stderr':r.stderr[-12000:]}
 except subprocess.TimeoutExpired:raise HTTPException(408,f'Code exceeded {CODE_TIMEOUT}s timeout.')

def next_time(kind,run_at=None,interval=1):
 nowdt=datetime.now(timezone.utc)
 if kind=='once':
  dt=datetime.fromisoformat(run_at.replace('Z','+00:00'))
  if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
  if dt<=nowdt:raise ValueError('Run time must be in the future.')
  return dt.astimezone(timezone.utc).isoformat()
 if kind=='hourly':return (nowdt+timedelta(hours=max(1,interval))).isoformat()
 if kind=='daily':return (nowdt+timedelta(days=1)).isoformat()
 raise ValueError('Schedule must be once, hourly or daily.')

def automation_loop():
 while not AUTOMATION_STOP.wait(30):
  try:
   ts=now();c=connect();rows=c.execute("SELECT * FROM automations WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at LIMIT 3",(ts,)).fetchall();c.close()
   for r in rows:
    # mark next before running to prevent duplicate trigger
    try:nxt=None if r['schedule_type']=='once' else next_time(r['schedule_type'],interval=r['interval_hours'] or 1)
    except:nxt=None
    with WRITE_LOCK:
     c=connect();c.execute("UPDATE automations SET enabled=?,next_run_at=?,updated_at=? WHERE id=?",(0 if nxt is None else 1,nxt or r['next_run_at'],now(),r['id']));runid=str(uuid.uuid4());c.execute("INSERT INTO automation_runs(id,automation_id,status,started_at) VALUES(?,?,?,?)",(runid,r['id'],'running',now()));c.commit();c.close()
    try:
     import asyncio
     result=asyncio.run(orchestrate(r['prompt'],remember=False,automation=True))['answer']
     with WRITE_LOCK:
      c=connect();c.execute("UPDATE automation_runs SET status='completed',result=?,completed_at=? WHERE id=?",(result,now(),runid));c.commit();c.close()
    except Exception as e:
     with WRITE_LOCK:
      c=connect();c.execute("UPDATE automation_runs SET status='failed',error=?,completed_at=? WHERE id=?",(str(e),now(),runid));c.commit();c.close()
  except Exception:pass

@app.on_event('startup')
def startup():
 global AUTOMATION_THREAD
 init_db();seed_governance();seed_phase2();AUTOMATION_STOP.clear();AUTOMATION_THREAD=threading.Thread(target=automation_loop,daemon=True);AUTOMATION_THREAD.start()
@app.on_event('shutdown')
def shutdown():AUTOMATION_STOP.set()

class Msg(BaseModel):message:str;remember:bool=True
class UrlBody(BaseModel):url:str
class ResearchBody(BaseModel):query:str;urls:list[str]
class DataAsk(BaseModel):dataset_id:str;question:str
class CodeBody(BaseModel):code:str
class CodeGen(BaseModel):request:str;language:str='python'
class ActionBody(BaseModel):action_type:str;payload:dict
class AutoBody(BaseModel):title:str;prompt:str;schedule_type:str;run_at:str|None=None;interval_hours:int|None=1
class NoteBody(BaseModel):title:str;body:str
class CalcBody(BaseModel):expression:str
class ObjectiveBody(BaseModel):title:str;description:str;priority:int=50
class AuthorityBody(BaseModel):scope:str;description:str;expires_at:str|None=None

class PortfolioBody(BaseModel):name:str;description:str;priority:int=50
class RecurringJobBody(BaseModel):name:str;scope:str;cadence:str
class DependencyBody(BaseModel):task_id:str;depends_on_task_id:str


@app.get('/',response_class=HTMLResponse)
async def home():return HTML
@app.get('/health')
async def health():
 c=connect();x=c.execute('PRAGMA quick_check').fetchone()[0];c.close();models=SETTINGS.ollama_readiness();ok=x=='ok' and models['ready'];payload={'ok':ok,'version':'7.3.1.1-evidence-grounded','integrity':x,'models':models};return JSONResponse(payload,status_code=200 if ok else 503)
@app.get('/api/status')
async def status():
 models=SETTINGS.ollama_readiness();installed=set(models['installed_models'])
 return {'version':'7.3.1.1-evidence-grounded','fast_ready':FAST_MODEL in installed,'deep_ready':DEEP_MODEL in installed,'memory_ready':EMBED_MODEL in installed,'model_readiness':models,**counts(),**governance_counts(),**phase2_counts(),**phase3_counts(),**orchestration_counts()}
@app.get('/api/selftest')
async def selftest():
 h=await health();h=json.loads(h.body) if isinstance(h,JSONResponse) else h;s=await status();required={'research','data','coding','actions','automation','memory','analyst','verifier','governor','executive','portfolio','auditor','operations','watchdog','performance','dependency','evaluator','artifact_curator','loop_manager'}
 c=connect()
 try:
  constitution_count=c.execute("SELECT COUNT(*) FROM org_constitution WHERE locked=1").fetchone()[0]
  department_count=c.execute("SELECT COUNT(*) FROM org_departments WHERE status='active'").fetchone()[0]
 finally:c.close()
 phase2_tables={'org_portfolios','org_task_dependencies','org_department_queue','org_autonomous_runs','org_recurring_jobs','org_performance_metrics','org_watchdog_events','org_execution_budget'}
 c2=connect()
 try:existing={r[0] for r in c2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 finally:c2.close()
 phase2_ok=phase2_tables<=existing
 phase3_tables={'org_artifacts','org_project_reviews','org_approval_requests'}
 phase3_ok=phase3_tables<=existing
 orchestration_tables={'org_orchestration_runs','org_agent_jobs','org_agent_inbox','org_context_summaries'}
 orchestration_ok=orchestration_tables<=existing and {'orchestrator','supervisor','compactor','economic','career','communications'}<=set(AGENTS)
 governance_ok=constitution_count>=9 and department_count>=6 and phase2_ok and phase3_ok and orchestration_ok
 return {'ok':h['ok'] and s['fast_ready'] and s['memory_ready'] and required<=set(AGENTS) and governance_ok,'health':h,'status':s,'agents_ok':required<=set(AGENTS),'agent_count':len(AGENTS),'governance_ok':governance_ok,'phase2_ok':phase2_ok,'phase3_ok':phase3_ok,'orchestration_ok':orchestration_ok,'constitution_rules':constitution_count,'departments':department_count,'code_guard_ok':validate_python('import math\nprint(math.sqrt(9))')[0] and not validate_python('import os')[0]}
@app.post('/api/chat')
async def chat(b:Msg):return await orchestrate(b.message.strip(),b.remember)
@app.get('/api/agents')
async def agents():return {'agents':AGENTS}
@app.get('/api/memory')
async def memory():
 c=connect();f=[dict(r) for r in c.execute("SELECT id,category,key,value FROM structured_facts WHERE active=1 ORDER BY updated_at DESC")];c.close();return {'facts':f,'counts':counts()}
@app.post('/api/documents/upload')
async def docupload(file:UploadFile=File(...)):
 data=await file.read(MAX_UPLOAD+1)
 if len(data)>MAX_UPLOAD:raise HTTPException(413,'File too large.')
 return await index_document(file.filename or 'document','file',None,parse_upload(file.filename or '',data))
@app.get('/api/documents')
async def docs():
 c=connect();x=[dict(r) for r in c.execute("SELECT id,name,source_type,source_ref,chunk_count,created_at FROM documents ORDER BY id DESC")];c.close();return x

@app.post('/api/research')
async def research(b:ResearchBody):
 urls=list(dict.fromkeys([u.strip() for u in b.urls if u.strip()]))[:5]
 if not b.query.strip() or not urls:raise HTTPException(400,'Provide a research question and at least one public URL.')
 rid=str(uuid.uuid4());sources=[]
 try:
  for u in urls:sources.append(await fetch_page(u))
  evidence='\n\n'.join(f"SOURCE {i+1}: {s['title']}\nURL: {s['url']}\n{s['text'][:18000]}" for i,s in enumerate(sources))
  ans,model=await llm(BASE_SYSTEM+" Cite source labels like [Source 1]. Do not invent unseen sources.",f"Research question: {b.query}\n\n{evidence[:60000]}",DEEP_MODEL)
  with WRITE_LOCK:
   c=connect();c.execute("INSERT INTO research_runs(id,query,sources_json,result,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)",(rid,b.query,json.dumps([{'title':s['title'],'url':s['url']} for s in sources]),ans,'completed',now(),now()));c.commit();c.close()
  return {'id':rid,'answer':ans,'sources':[{'title':s['title'],'url':s['url']} for s in sources],'model':model}
 except Exception as e:
  with WRITE_LOCK:
   c=connect();c.execute("INSERT OR REPLACE INTO research_runs(id,query,sources_json,result,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)",(rid,b.query,json.dumps([]),str(e),'failed',now(),now()));c.commit();c.close()
  raise
@app.get('/api/research')
async def research_history():
 c=connect();x=[dict(r) for r in c.execute("SELECT id,query,sources_json,result,status,created_at FROM research_runs ORDER BY created_at DESC LIMIT 20")];c.close();return x

@app.post('/api/datasets/upload')
async def dataset_upload(file:UploadFile=File(...)):
 data=await file.read(MAX_UPLOAD+1)
 if len(data)>MAX_UPLOAD:raise HTTPException(413,'Dataset too large.')
 ext=Path(file.filename or '').suffix.lower()
 did=str(uuid.uuid4());stored=did+ext;path=DATASETS/stored
 if ext=='.csv':df=pd.read_csv(io.BytesIO(data))
 elif ext=='.json':df=pd.read_json(io.BytesIO(data))
 else:raise HTTPException(400,'Data Agent supports CSV and JSON.')
 if len(df)>250000:raise HTTPException(413,'Dataset exceeds 250,000 rows in this build.')
 if len(df.columns)>500:raise HTTPException(413,'Dataset exceeds 500 columns in this build.')
 path.write_bytes(data);cols=[str(x) for x in df.columns]
 with WRITE_LOCK:
  c=connect();c.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?)",(did,file.filename or stored,stored,ext[1:],len(df),len(df.columns),json.dumps(cols),now()));c.commit();c.close()
 # Evidence arrival automatically releases Data missions that were safely blocked for missing evidence.
 with WRITE_LOCK:
  c=connect()
  try:
   blocked=[r["task_id"] for r in c.execute("SELECT task_id FROM org_department_queue WHERE department='Data' AND status='blocked_evidence'")]
   if blocked:
    c.execute("UPDATE org_department_queue SET status='queued',available_at=?,lease_until=NULL,updated_at=? WHERE department='Data' AND status='blocked_evidence'",(now(),now()))
    for tid in blocked:c.execute("UPDATE org_project_tasks SET status='planned',updated_at=? WHERE id=?",(now(),tid))
    c.commit()
  finally:c.close()
 if blocked:org_event('evidence_arrived_tasks_requeued','data',did,{'requeued_tasks':len(blocked)})
 return {'id':did,'name':file.filename,'rows':len(df),'columns':cols}
def load_dataset(did):
 c=connect();r=c.execute("SELECT * FROM datasets WHERE id=?",(did,)).fetchone();c.close()
 if not r:raise HTTPException(404,'Dataset not found.')
 p=DATASETS/r['stored_name'];df=pd.read_csv(p) if r['kind']=='csv' else pd.read_json(p);return dict(r),df
@app.get('/api/datasets')
async def datasets():
 c=connect();x=[dict(r) for r in c.execute("SELECT id,name,kind,row_count,column_count,created_at FROM datasets ORDER BY created_at DESC")];c.close();return x
@app.get('/api/datasets/{did}/summary')
async def dataset_summary(did:str):
 meta,df=load_dataset(did);desc=df.describe(include='all').fillna('').astype(str).to_dict();missing={str(k):int(v) for k,v in df.isna().sum().items()};return {'meta':meta,'dtypes':{str(k):str(v) for k,v in df.dtypes.items()},'missing':missing,'describe':desc,'sample':df.head(8).fillna('').astype(str).to_dict(orient='records')}
@app.post('/api/datasets/ask')
async def dataset_ask(b:DataAsk):
 meta,df=load_dataset(b.dataset_id);sample=df.head(30).fillna('').astype(str).to_csv(index=False);summary=str(df.describe(include='all').fillna('').astype(str).to_dict())[:14000]
 ans,model=await llm(BASE_SYSTEM+" You are the Data Agent. Do not claim calculations not shown in the supplied summary/sample.",f"Dataset {meta['name']} rows={len(df)} columns={list(df.columns)}\nSUMMARY:\n{summary}\nSAMPLE:\n{sample[:12000]}\nQUESTION:\n{b.question}",DEEP_MODEL);return {'answer':ans,'model':model}

@app.post('/api/code/generate')
async def code_generate(b:CodeGen):
 ans,model=await llm(BASE_SYSTEM+" You are the Coding Agent. Return code and a short explanation. Prefer Python unless requested otherwise. Do not claim it was executed.",b.request,DEEP_MODEL);return {'answer':ans,'model':model}
@app.post('/api/code/validate')
async def code_validate(b:CodeBody):ok,msg=validate_python(b.code);return {'ok':ok,'message':msg}
@app.post('/api/code/run')
async def code_run(b:CodeBody):return run_python(b.code)
@app.get('/api/code/files')
async def code_files():
 c=connect();x=[dict(r) for r in c.execute("SELECT id,name,language,created_at,updated_at FROM code_files ORDER BY updated_at DESC")];c.close();return x

@app.post('/api/actions/propose')
async def action_propose(b:ActionBody):
 if b.action_type not in {'create_note','save_code_file'}:raise HTTPException(400,'Unsupported action type.')
 aid=str(uuid.uuid4())
 with WRITE_LOCK:
  c=connect();c.execute("INSERT INTO action_queue VALUES(?,?,?,?,?,?,?)",(aid,b.action_type,json.dumps(b.payload),'pending',now(),None,None));c.commit();c.close()
 return {'id':aid,'status':'pending'}
@app.get('/api/actions')
async def actions():
 c=connect();x=[dict(r) for r in c.execute("SELECT * FROM action_queue ORDER BY created_at DESC LIMIT 50")];c.close();return x
@app.post('/api/actions/{aid}/approve')
async def action_approve(aid:str):
 with WRITE_LOCK:
  c=connect();r=c.execute("SELECT * FROM action_queue WHERE id=? AND status='pending'",(aid,)).fetchone()
  if not r:c.close();raise HTTPException(404,'Pending action not found.')
  p=json.loads(r['payload_json']);result=''
  if r['action_type']=='create_note':
   title=str(p.get('title','Untitled'))[:200];body=str(p.get('body',''))[:50000]
   if not body:c.close();raise HTTPException(400,'Note body is empty.')
   ts=now();c.execute("INSERT INTO notes(title,body,created_at,updated_at) VALUES(?,?,?,?)",(title,body,ts,ts));result='Note created.'
  elif r['action_type']=='save_code_file':
   name=Path(str(p.get('name','script.py'))).name
   if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name):c.close();raise HTTPException(400,'Invalid filename.')
   code=str(p.get('code',''))[:100000]
   if name.endswith('.py'):
    ok,msg=validate_python(code)
    if not ok:c.close();raise HTTPException(400,msg)
   path=CODE/name;path.write_text(code,encoding='utf-8');fid=str(uuid.uuid4());ts=now();c.execute("INSERT INTO code_files VALUES(?,?,?,?,?,?)",(fid,name,'python' if name.endswith('.py') else 'text',str(path),ts,ts));result=f'Saved {name}.'
  c.execute("UPDATE action_queue SET status='approved',resolved_at=?,result=? WHERE id=?",(now(),result,aid));c.commit();c.close();return {'ok':True,'result':result}
@app.post('/api/actions/{aid}/reject')
async def action_reject(aid:str):
 with WRITE_LOCK:
  c=connect();cur=c.execute("UPDATE action_queue SET status='rejected',resolved_at=?,result='Rejected by user.' WHERE id=? AND status='pending'",(now(),aid));c.commit();c.close()
 if not cur.rowcount:raise HTTPException(404,'Pending action not found.')
 return {'ok':True}

@app.post('/api/automations')
async def automation_create(b:AutoBody):
 if not b.title.strip() or not b.prompt.strip():raise HTTPException(400,'Title and prompt are required.')
 kind=b.schedule_type.lower();interval=max(1,int(b.interval_hours or 1))
 try:nxt=next_time(kind,b.run_at,interval)
 except Exception as e:raise HTTPException(400,str(e))
 aid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect();c.execute("INSERT INTO automations VALUES(?,?,?,?,?,?,?,?,?,?)",(aid,b.title[:200],b.prompt[:10000],kind,interval,b.run_at,nxt,1,ts,ts));c.commit();c.close()
 return {'id':aid,'next_run_at':nxt}
@app.get('/api/automations')
async def automations():
 c=connect();a=[dict(r) for r in c.execute("SELECT * FROM automations ORDER BY created_at DESC")];runs=[dict(r) for r in c.execute("SELECT * FROM automation_runs ORDER BY started_at DESC LIMIT 30")];c.close();return {'automations':a,'runs':runs}
@app.post('/api/automations/{aid}/toggle')
async def automation_toggle(aid:str):
 with WRITE_LOCK:
  c=connect();r=c.execute("SELECT enabled FROM automations WHERE id=?",(aid,)).fetchone()
  if not r:c.close();raise HTTPException(404,'Automation not found.')
  c.execute("UPDATE automations SET enabled=?,updated_at=? WHERE id=?",(0 if r['enabled'] else 1,now(),aid));c.commit();c.close()
 return {'ok':True}

ALLOWED_BINOPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow};ALLOWED_UNARY={ast.UAdd:operator.pos,ast.USub:operator.neg}
def safe_calc(expr):
 tree=ast.parse(expr,mode='eval')
 def ev(n):
  if isinstance(n,ast.Expression):return ev(n.body)
  if isinstance(n,ast.Constant) and type(n.value) in {int,float}:return n.value
  if isinstance(n,ast.BinOp) and type(n.op) in ALLOWED_BINOPS:return ALLOWED_BINOPS[type(n.op)](ev(n.left),ev(n.right))
  if isinstance(n,ast.UnaryOp) and type(n.op) in ALLOWED_UNARY:return ALLOWED_UNARY[type(n.op)](ev(n.operand))
  raise ValueError('Only arithmetic is allowed.')
 return ev(tree)
@app.post('/api/calc')
async def calc(b:CalcBody):
 try:return {'result':safe_calc(b.expression)}
 except Exception as e:raise HTTPException(400,str(e))
@app.get('/api/notes')
async def notes():
 c=connect();x=[dict(r) for r in c.execute("SELECT id,title,body,created_at FROM notes ORDER BY id DESC")];c.close();return x


@app.get('/api/governance')
async def governance():
 c=connect()
 try:
  constitution=[dict(r) for r in c.execute("SELECT rule_key,rule_text,locked FROM org_constitution ORDER BY id")];departments=[dict(r) for r in c.execute("SELECT id,name,mission,status FROM org_departments ORDER BY name")];grants=[dict(r) for r in c.execute("SELECT id,scope,description,status,expires_at,created_at FROM authority_grants ORDER BY created_at DESC LIMIT 50")];events=[dict(r) for r in c.execute("SELECT id,event_type,actor,subject,details_json,created_at FROM org_events ORDER BY created_at DESC LIMIT 50")]
 finally:c.close()
 return {'constitution':constitution,'departments':departments,'authority_grants':grants,'events':events}
@app.post('/api/objectives')
async def create_objective(b:ObjectiveBody):
 title=b.title.strip()[:300];desc=b.description.strip()[:10000]
 if not title or not desc:raise HTTPException(400,'Objective title and description are required.')
 oid=str(uuid.uuid4());ts=now();priority=max(1,min(100,int(b.priority)))
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_objectives(id,title,description,status,priority,created_at,updated_at) VALUES(?,?,?,'active',?,?,?)",(oid,title,desc,priority,ts,ts));c.commit()
  finally:c.close()
 org_event('objective_created','user',oid,{'title':title,'priority':priority});return {'id':oid,'status':'active'}
@app.get('/api/objectives')
async def objectives():
 c=connect()
 try:rows=[dict(r) for r in c.execute("SELECT * FROM org_objectives ORDER BY priority DESC,created_at DESC")]
 finally:c.close()
 return rows
@app.post('/api/objectives/{oid}/pause')
async def pause_objective(oid:str):
 with WRITE_LOCK:
  c=connect()
  try:cur=c.execute("UPDATE org_objectives SET status='paused',updated_at=? WHERE id=? AND status='active'",(now(),oid));c.commit()
  finally:c.close()
 if not cur.rowcount:raise HTTPException(404,'Active objective not found.')
 org_event('objective_paused','user',oid,{});return {'ok':True}
@app.get('/api/projects')
async def projects():
 c=connect()
 try:ps=[dict(r) for r in c.execute("SELECT * FROM org_projects ORDER BY created_at DESC LIMIT 100")];ts=[dict(r) for r in c.execute("SELECT * FROM org_project_tasks ORDER BY project_id,sequence,id")]
 finally:c.close()
 by={}
 for t in ts:by.setdefault(t['project_id'],[]).append(t)
 for p in ps:p['tasks']=by.get(p['id'],[])
 return ps
@app.post('/api/authority')
async def create_authority(b:AuthorityBody):
 scope=b.scope.strip()[:300];desc=b.description.strip()[:5000];allowed={'internal_planning','internal_research','internal_data_analysis','internal_code_drafting','internal_document_creation'}
 if scope not in allowed:raise HTTPException(400,'Phase 1 permits only narrow internal authority grants.')
 aid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO authority_grants(id,scope,description,status,expires_at,created_at,updated_at) VALUES(?,?,?,'active',?,?,?)",(aid,scope,desc,b.expires_at,ts,ts));c.commit()
  finally:c.close()
 org_event('authority_granted','user',aid,{'scope':scope});return {'id':aid,'scope':scope,'status':'active'}
@app.post('/api/authority/{aid}/revoke')
async def revoke_authority(aid:str):
 with WRITE_LOCK:
  c=connect()
  try:cur=c.execute("UPDATE authority_grants SET status='revoked',updated_at=? WHERE id=? AND status='active'",(now(),aid));c.commit()
  finally:c.close()
 if not cur.rowcount:raise HTTPException(404,'Active authority grant not found.')
 org_event('authority_revoked','user',aid,{});return {'ok':True}

def _extract_json_object(text):
 text=(text or "").strip()
 if not text:return None
 text=re.sub(r"^```(?:json)?\s*","",text,flags=re.I)
 text=re.sub(r"\s*```$","",text)
 try:
  obj=json.loads(text)
  return obj if isinstance(obj,dict) else None
 except Exception:
  pass
 start=text.find("{")
 if start<0:return None
 depth=0;in_str=False;esc=False
 for i,ch in enumerate(text[start:],start):
  if in_str:
   if esc:esc=False
   elif ch=="\\":esc=True
   elif ch=='"':in_str=False
   continue
  if ch=='"':in_str=True
  elif ch=="{":depth+=1
  elif ch=="}":
   depth-=1
   if depth==0:
    candidate=text[start:i+1]
    candidate=re.sub(r",\s*([}\]])",r"\1",candidate)
    candidate=candidate.replace("“",'"').replace("”",'"').replace("’","'")
    try:
     obj=json.loads(candidate)
     return obj if isinstance(obj,dict) else None
    except Exception:
     return None
 return None

def _validate_org_plan(plan,valid_depts,max_tasks=6):
 if not isinstance(plan,dict):return None,"plan is not an object"
 title=str(plan.get("project_title","")).strip()[:300]
 desc=str(plan.get("project_description","")).strip()[:10000]
 dept=str(plan.get("department","")).strip()[:200]
 tasks=plan.get("tasks",[])
 if not title:return None,"missing project_title"
 if not desc:return None,"missing project_description"
 if dept not in valid_depts:return None,"invalid department"
 if not isinstance(tasks,list) or not (1<=len(tasks)<=max_tasks):return None,"invalid tasks list"
 clean=[]
 for t in tasks:
  if not isinstance(t,dict):continue
  tt=str(t.get("title","")).strip()[:300]
  td=str(t.get("description","")).strip()[:5000]
  if tt:clean.append({"title":tt,"description":td})
 if not clean:return None,"no valid tasks"
 clean=clean[:max_tasks]
 # Guardrail is intent-aware: explicit prohibitions are allowed, proposed actions are blocked.
 def strip_safety_negations(s):
  s=norm(s)
  patterns=[
   r"\bdo not\s+(?:make\s+)?(?:a\s+)?(?:purchase|purchases|payment|payments|transfer|transfers|publish|send|delete|change|expand)\b[^.;\n]*",
   r"\bdon't\s+(?:make\s+)?(?:a\s+)?(?:purchase|purchases|payment|payments|transfer|transfers|publish|send|delete|change|expand)\b[^.;\n]*",
   r"\bmust not\s+(?:make\s+)?(?:a\s+)?(?:purchase|purchases|payment|payments|transfer|transfers|publish|send|delete|change|expand)\b[^.;\n]*",
   r"\bnever\s+(?:make\s+)?(?:a\s+)?(?:purchase|purchases|payment|payments|transfer|transfers|publish|send|delete|change|expand)\b[^.;\n]*",
   r"\b(?:purchases?|payments?|transfers?|external communications?|publishing|account changes?)\s+(?:are|remain)\s+(?:prohibited|forbidden|blocked)\b[^.;\n]*",
   r"\bwithout (?:explicit )?(?:user )?approval\b[^.;\n]*"
  ]
  for pat in patterns:s=re.sub(pat," ",s,flags=re.I)
  return re.sub(r"\s+"," ",s).strip()

 blob=strip_safety_negations(title+" "+desc+" "+json.dumps(clean))
 prohibited=[
  r"\bsend (?:an? )?(?:email|message)\b",
  r"\b(?:make|execute|initiate|process)\s+(?:a\s+)?(?:purchase|payment|transfer)\b",
  r"\b(?:purchase|buy)\s+\S+",
  r"\bpublish\b",
  r"\bdelete (?:a |the )?(?:file|folder|document|data)\b",
  r"\bchange (?:a |the )?(?:password|account|permission|permissions)\b",
  r"\btransfer money\b",
  r"\bexpand (?:its |our |the )?authority\b",
  r"\bgrant itself\b"
 ]
 if any(re.search(pat,blob,re.I) for pat in prohibited):return None,"prohibited action language"
 return {"project_title":title,"project_description":desc,"department":dept,"tasks":clean},"ok"

def _deterministic_fallback_plan(obj,depts):
 names=[d["name"] for d in depts]
 preferred="Strategy" if "Strategy" in names else (names[0] if names else "Strategy")
 title=(str(obj["title"]).strip() or "Strategic Objective")[:220]
 desc=(str(obj["description"]).strip() or "Develop an internal execution plan.")[:3000]
 tasks=[
  {"title":"Establish economic baseline","description":"Organize known facts, assumptions, constraints, assets, liabilities, income sources and missing information relevant to the objective."},
  {"title":"Define measurable outcomes","description":"Translate the objective into measurable internal targets, milestones and decision criteria."},
  {"title":"Map opportunity portfolio","description":"Identify and rank internal workstreams by expected impact, feasibility, urgency and dependencies."},
  {"title":"Create execution queue","description":"Break the highest-value workstreams into bounded internal tasks for the appropriate ORQEVIA departments."},
  {"title":"Define review metrics","description":"Specify what ORQEVIA should measure to determine whether the plan is improving outcomes and where iteration is required."}
 ]
 return {"project_title":f"{title} — Internal Execution Plan"[:300],
         "project_description":"Safe internal execution plan derived from the active objective. All consequential external and financial actions remain outside autonomous authority.",
         "department":preferred,"tasks":tasks[:6]}

async def _repair_org_plan(raw,obj,depts):
 prompt=f"""Repair the following attempted organization plan into STRICT JSON only.
Do not add commentary or markdown.

OBJECTIVE:
Title: {obj['title']}
Description: {obj['description']}

VALID DEPARTMENTS:
{json.dumps([d['name'] for d in depts])}

REQUIRED JSON:
{{
 "project_title":"...",
 "project_description":"...",
 "department":"one valid department exactly",
 "tasks":[{{"title":"...","description":"..."}}]
}}

Rules:
- 1 to 6 tasks.
- INTERNAL planning only.
- No external messages, purchases, publishing, account changes, destructive actions, financial transactions, or authority expansion.

ATTEMPT TO REPAIR:
{raw[:12000]}
"""
 try:
  d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
  return d['message']['content'].strip()
 except Exception:
  return ""

@app.post('/api/org/cycle')
async def organization_cycle():
 c=connect()
 try:
  obj=c.execute("SELECT * FROM org_objectives WHERE status='active' ORDER BY priority DESC,created_at LIMIT 1").fetchone()
  depts=[dict(r) for r in c.execute("SELECT name,mission FROM org_departments WHERE status='active' ORDER BY name")]
 finally:c.close()
 if not obj:raise HTTPException(400,'Create an active objective first.')
 valid_depts={d['name'] for d in depts}
 if not valid_depts:raise HTTPException(503,'No active departments are available.')

 prompt=f"""You are ORQEVIA V7 Phase 2's Executive Orchestrator under a strict constitution.
OBJECTIVE:
Title: {obj['title']}
Description: {obj['description']}
Priority: {obj['priority']}

AVAILABLE DEPARTMENTS:
{json.dumps(depts)}

Return STRICT JSON only:
{{
 "project_title":"...",
 "project_description":"...",
 "department":"one available department name exactly",
 "tasks":[{{"title":"...","description":"..."}}]
}}

Rules:
- INTERNAL planning only.
- 1 to 6 tasks.
- Do not send messages, purchase, publish, change accounts, delete external files, make payments, transfer money, or expand authority.
"""
 raw="";source="model";reason="";plan=None

 try:
  d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
  raw=d['message']['content'].strip()
  parsed=_extract_json_object(raw)
  plan,reason=_validate_org_plan(parsed,valid_depts,6)
 except Exception as e:
  reason="model exception: "+str(e)

 if not plan:
  org_event('organization_plan_parse_retry','executive',obj['id'],{'reason':reason,'raw_preview':raw[:2000]})
  repaired=await _repair_org_plan(raw,obj,depts)
  parsed=_extract_json_object(repaired)
  plan,repair_reason=_validate_org_plan(parsed,valid_depts,6)
  if plan:source="repair"
  else:reason=repair_reason

 if not plan:
  source="deterministic_fallback"
  fallback=_deterministic_fallback_plan(obj,depts)
  plan,fallback_reason=_validate_org_plan(fallback,valid_depts,6)
  if not plan:
   watchdog_event('critical','organization_fallback_failed',obj['id'],{'reason':fallback_reason})
   raise HTTPException(503,'Organization cycle failed after model, repair, and deterministic fallback.')
  watchdog_event('warning','organization_model_fallback_used',obj['id'],{'reason':reason,'raw_preview':raw[:2000]})

 pid=str(uuid.uuid4());ts=now()
 with WRITE_LOCK:
  c=connect()
  try:
   c.execute("INSERT INTO org_projects(id,objective_id,title,description,status,department,created_at,updated_at) VALUES(?,?,?,?, 'draft',?,?,?)",
             (pid,obj['id'],plan['project_title'],plan['project_description'],plan['department'],ts,ts))
   for i,t in enumerate(plan['tasks']):
    c.execute("INSERT INTO org_project_tasks(id,project_id,title,description,status,sequence,created_at,updated_at) VALUES(?,?,?,?, 'planned',?,?,?)",
              (str(uuid.uuid4()),pid,t['title'],t.get('description',''),i+1,ts,ts))
   c.commit()
  finally:c.close()
 org_event('organization_cycle_completed','executive',pid,{'objective_id':obj['id'],'department':plan['department'],'task_count':len(plan['tasks']),'plan_source':source})
 return {'project_id':pid,'objective_id':obj['id'],'title':plan['project_title'],'department':plan['department'],'tasks':plan['tasks'],'status':'draft','plan_source':source}

@app.post('/api/portfolios')
async def create_portfolio(b:PortfolioBody):
 name=b.name.strip()[:300];desc=b.description.strip()[:10000]
 if not name or not desc:raise HTTPException(400,'Name and description required.')
 pid=str(uuid.uuid4());ts=now();priority=max(1,min(100,int(b.priority)))
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_portfolios(id,name,description,status,priority,created_at,updated_at) VALUES(?,?,?,'active',?,?,?)",(pid,name,desc,priority,ts,ts));c.commit()
  finally:c.close()
 org_event('portfolio_created','user',pid,{'name':name,'priority':priority})
 return {'id':pid,'status':'active'}

@app.get('/api/portfolios')
async def portfolios():
 c=connect()
 try:return [dict(r) for r in c.execute("SELECT * FROM org_portfolios ORDER BY priority DESC,created_at DESC")]
 finally:c.close()

@app.post('/api/dependencies')
async def add_dependency(b:DependencyBody):
 if b.task_id==b.depends_on_task_id:raise HTTPException(400,'A task cannot depend on itself.')
 with WRITE_LOCK:
  c=connect()
  try:
   a=c.execute("SELECT 1 FROM org_project_tasks WHERE id=?",(b.task_id,)).fetchone()
   d=c.execute("SELECT 1 FROM org_project_tasks WHERE id=?",(b.depends_on_task_id,)).fetchone()
   if not a or not d:raise HTTPException(404,'Task not found.')
   c.execute("INSERT OR IGNORE INTO org_task_dependencies(task_id,depends_on_task_id,created_at) VALUES(?,?,?)",(b.task_id,b.depends_on_task_id,now()));c.commit()
  finally:c.close()
 org_event('dependency_added','user',b.task_id,{'depends_on':b.depends_on_task_id})
 return {'ok':True}

@app.get('/api/queue')
async def queue_view():
 c=connect()
 try:
  return [dict(r) for r in c.execute("""SELECT q.*,t.title,t.description,t.project_id FROM org_department_queue q
                                        JOIN org_project_tasks t ON t.id=q.task_id
                                        ORDER BY CASE q.status WHEN 'queued' THEN 0 ELSE 1 END,q.priority DESC,q.created_at""")]
 finally:c.close()

@app.post('/api/projects/{pid}/enqueue')
async def enqueue_project(pid:str):
 c=connect()
 try:
  p=c.execute("SELECT department FROM org_projects WHERE id=?",(pid,)).fetchone()
  tasks=[dict(r) for r in c.execute("SELECT id,status,sequence FROM org_project_tasks WHERE project_id=? ORDER BY sequence",(pid,))]
 finally:c.close()
 if not p:raise HTTPException(404,'Project not found.')
 dept=p['department'] or 'Strategy'
 count=0
 for t in tasks:
  if t['status'] in ('planned','active'):
   queue_task(t['id'],dept,50)
   count+=1
 org_event('project_enqueued','user',pid,{'tasks':count,'department':dept})
 return {'queued':count}

@app.post('/api/recurring-jobs')
async def create_recurring_job(b:RecurringJobBody):
 cadence=b.cadence.strip().lower()
 if cadence not in {'hourly','daily'}:raise HTTPException(400,'Phase 2 supports hourly or daily internal jobs.')
 allowed={'internal_planning','internal_research','internal_data_analysis','internal_code_drafting','internal_document_creation'}
 if b.scope not in allowed:raise HTTPException(400,'Recurring scope must be internal and explicitly allowed.')
 jid=str(uuid.uuid4());ts=now()
 next_run=(datetime.now(timezone.utc)+timedelta(hours=1 if cadence=='hourly' else 24)).isoformat()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_recurring_jobs(id,name,scope,cadence,status,next_run_at,last_run_at,created_at,updated_at) VALUES(?,?,?,?,'active',?,NULL,?,?)",(jid,b.name.strip()[:300],b.scope,cadence,next_run,ts,ts));c.commit()
  finally:c.close()
 org_event('recurring_job_created','user',jid,{'scope':b.scope,'cadence':cadence})
 return {'id':jid,'next_run_at':next_run}

@app.get('/api/recurring-jobs')
async def recurring_jobs():
 c=connect()
 try:return [dict(r) for r in c.execute("SELECT * FROM org_recurring_jobs ORDER BY created_at DESC")]
 finally:c.close()

@app.get('/api/performance')
async def performance():
 c=connect()
 try:
  metrics=[dict(r) for r in c.execute("SELECT * FROM org_performance_metrics ORDER BY recorded_at DESC LIMIT 200")]
  runs=[dict(r) for r in c.execute("SELECT * FROM org_autonomous_runs ORDER BY started_at DESC LIMIT 100")]
  wd=[dict(r) for r in c.execute("SELECT * FROM org_watchdog_events ORDER BY created_at DESC LIMIT 100")]
 finally:c.close()
 return {'metrics':metrics,'runs':runs,'watchdog':wd}

@app.post('/api/org/autonomous-cycle')
async def autonomous_cycle():
 ok,reason=watchdog_can_run()
 if not ok:
  watchdog_event('warning','cycle_blocked',None,{'reason':reason})
  raise HTTPException(429,'Watchdog blocked autonomous cycle: '+reason)

 run_id=str(uuid.uuid4());started=now()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_autonomous_runs(id,status,started_at,cycles,tasks_created,tasks_completed,failures) VALUES(?,'running',?,0,0,0,0)",(run_id,started));c.commit()
  finally:c.close()

 created=0;completed=0;failures=0;cycles=0;summary=[]
 try:
  for _ in range(min(3,PHASE2_MAX_PROJECTS)):
   cycles+=1
   item=select_next_queue_item()
   if not item:break
   task_id=item['task_id']
   with WRITE_LOCK:
    c=connect()
    try:
     c.execute("UPDATE org_department_queue SET status='leased',lease_until=?,updated_at=? WHERE id=?",
               ((datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),now(),item['id']))
     c.execute("UPDATE org_project_tasks SET status='active',updated_at=? WHERE id=?",(now(),task_id));c.commit()
    finally:c.close()

   prompt=f"""You are ORQEVIA V7 Phase 2 performing one INTERNAL task.
Department: {item['department']}
Task: {item['title']}
Description: {item['description']}

Return a concise internal deliverable only.
Do not send messages, purchase, publish, change accounts, delete external files, or expand authority.
"""
   try:
    d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
    result=d['message']['content'].strip()[:20000]
    with WRITE_LOCK:
     c=connect()
     try:
      c.execute("UPDATE org_project_tasks SET status='completed',description=COALESCE(description,'')||?,updated_at=? WHERE id=?",
                ('\\n\\nPHASE2 RESULT:\\n'+result,now(),task_id))
      c.execute("UPDATE org_department_queue SET status='completed',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']))
      c.commit()
     finally:c.close()
    completed+=1
    summary.append({'task':item['title'],'status':'completed'})
    record_metric('department',item['department'],'tasks_completed',1)
   except Exception as e:
    failures+=1
    with WRITE_LOCK:
     c=connect()
     try:
      c.execute("UPDATE org_project_tasks SET status='planned',updated_at=? WHERE id=?",(now(),task_id))
      c.execute("UPDATE org_department_queue SET status='queued',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']))
      c.commit()
     finally:c.close()
    watchdog_event('warning','task_failure',task_id,{'error':str(e)})
    summary.append({'task':item['title'],'status':'failed'})
    break

  final_status='completed' if failures==0 else 'partial'
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_autonomous_runs SET status=?,completed_at=?,cycles=?,tasks_created=?,tasks_completed=?,failures=?,summary=? WHERE id=?",
                 (final_status,now(),cycles,created,completed,failures,json.dumps(summary),run_id));c.commit()
   finally:c.close()
  org_event('autonomous_cycle_completed','operations',run_id,{'cycles':cycles,'completed':completed,'failures':failures})
  return {'run_id':run_id,'status':final_status,'cycles':cycles,'tasks_completed':completed,'failures':failures,'summary':summary}
 except Exception as e:
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_autonomous_runs SET status='failed',completed_at=?,failures=failures+1,summary=? WHERE id=?",(now(),str(e),run_id));c.commit()
   finally:c.close()
  watchdog_event('critical','autonomous_cycle_crash',run_id,{'error':str(e)})
  raise




def local_dataset_inventory(limit=20):
 c=connect()
 try:
  rows=[dict(r) for r in c.execute("SELECT id,name,stored_name,kind,row_count,column_count,columns_json,created_at FROM datasets ORDER BY created_at DESC LIMIT ?",(int(limit),))]
 finally:c.close()
 return rows

def _dataset_evidence_packet(max_rows=20,max_chars=13500):
 rows=local_dataset_inventory()
 if not rows:
  return "", []
 blocks=[]
 source_ids=[]
 for meta in rows[:3]:
  source_ids.append(meta["id"])
  try:
   m,df=load_dataset(meta["id"])
   cols=[str(x) for x in df.columns]
   sample=df.head(max_rows).fillna("").astype(str).to_csv(index=False)
   # Real computed descriptive statistics; this text is the only quantitative evidence given to the model.
   try:
    desc=json.dumps(df.describe(include="all").fillna("").astype(str).to_dict(),ensure_ascii=False)[:5000]
   except Exception:
    desc="Descriptive statistics unavailable."
   block=(
    f"SOURCE DATASET: {meta['name']} [{meta['id']}]\n"
    f"Kind: {meta['kind']}; rows: {meta['row_count']}; columns: {meta['column_count']}\n"
    f"Columns: {', '.join(cols)}\n"
    f"ACTUAL SAMPLE ROWS (up to {max_rows}):\n{sample}\n"
    f"ACTUAL PANDAS DESCRIBE OUTPUT:\n{desc}"
   )
   blocks.append(block)
  except Exception as e:
   blocks.append(f"SOURCE DATASET: {meta['name']} [{meta['id']}]\nMetadata exists, but loading failed: {str(e)[:300]}")
 packet="\n\n---\n\n".join(blocks)
 return packet[:max_chars],source_ids

def evidence_packet_for_specialist(specialist,item):
 if specialist=="data":
  packet,ids=_dataset_evidence_packet()
  return packet,{"kind":"local_datasets","source_ids":ids,"source_count":len(ids)}
 # For non-data specialists, the mission brief itself, objective/project/task text,
 # and previously verified compacted context are available. No external evidence is implied.
 return "",{"kind":"mission_context_only","source_ids":[],"source_count":0}

def mark_evidence_blocked(item,run_id,jid,reason,specialist):
 content=(
  "DATA_REQUIRED\n\n"
  "Result\n"
  "ORQEVIA cannot perform this quantitative mission yet because no verified local dataset is available.\n\n"
  "Evidence actually used\n"
  "None. ORQEVIA intentionally refused to invent transaction records, databases, users, amounts, percentages, locations, or behavioral observations.\n\n"
  "Assumptions and uncertainties\n"
  "No analytical conclusion is made until the required evidence is supplied.\n\n"
  "Recommended INTERNAL next step\n"
  "Upload a CSV or JSON dataset in the Data tab. For spending analysis, include at minimum a date, amount, currency, and category or merchant field. "
  "After upload, ORQEVIA will automatically release evidence-blocked Data tasks back to the queue."
 )
 aid=create_artifact(item["task_id"],item["project_id"],run_id,item["title"],content,"blocked_evidence",0,reason)
 with WRITE_LOCK:
  c=connect()
  try:
   c.execute("UPDATE org_project_tasks SET status='blocked_evidence',updated_at=? WHERE id=?",(now(),item["task_id"]))
   c.execute("UPDATE org_department_queue SET status='blocked_evidence',lease_until=NULL,updated_at=? WHERE id=?",(now(),item["id"]))
   c.commit()
  finally:c.close()
 update_agent_job(jid,status="blocked_evidence",attempts=0,last_status=reason,result=content,artifact_id=aid,complete=True)
 push_agent_inbox(run_id,jid,"data_required",{"task":item["title"],"specialist":specialist,"artifact_id":aid,"reason":reason})
 org_event("agent_job_evidence_blocked","grounding_guard",jid,{"task_id":item["task_id"],"reason":reason})
 return {"job_id":jid,"task":item["title"],"specialist":specialist,"route_reason":item.get("route_reason",""),"status":"blocked_evidence","artifact_id":aid,"score":0,"attempts":0,"retries":0,"reason":reason}

def orchestration_context(project_id):
 c=connect()
 try:
  r=c.execute("SELECT summary FROM org_context_summaries WHERE scope_type='project' AND scope_id=? ORDER BY created_at DESC LIMIT 1",(project_id,)).fetchone()
  return r['summary'] if r else ''
 finally:c.close()

def create_agent_job(run_id,item,specialist,brief,max_attempts):
 jid=str(uuid.uuid4());ts=now()
 c=connect()
 try:
  p=c.execute("SELECT p.*,o.title objective_title,o.description objective_description,o.id objective_id FROM org_projects p LEFT JOIN org_objectives o ON o.id=p.objective_id WHERE p.id=?",(item['project_id'],)).fetchone()
 finally:c.close()
 objective_id=p['objective_id'] if p else None
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_agent_jobs(id,orchestration_run_id,task_id,project_id,objective_id,specialist,status,brief,attempts,max_attempts,last_status,started_at,updated_at) VALUES(?,?,?,?,?,?, 'running',?,0,?,'dispatched',?,?)",(jid,run_id,item['task_id'],item['project_id'],objective_id,specialist,brief,max_attempts,ts,ts));c.commit()
  finally:c.close()
 org_event('agent_job_dispatched','orchestrator',jid,{'specialist':specialist,'task_id':item['task_id'],'route_reason':item.get('route_reason','')})
 return jid

def update_agent_job(jid,*,status=None,attempts=None,last_status=None,result=None,artifact_id=None,complete=False):
 sets=[];vals=[]
 for col,val in [('status',status),('attempts',attempts),('last_status',last_status),('result',result),('artifact_id',artifact_id)]:
  if val is not None:sets.append(f"{col}=?");vals.append(val)
 sets.append('updated_at=?');vals.append(now())
 if complete:sets.append('completed_at=?');vals.append(now())
 vals.append(jid)
 with WRITE_LOCK:
  c=connect()
  try:c.execute("UPDATE org_agent_jobs SET "+','.join(sets)+" WHERE id=?",tuple(vals));c.commit()
  finally:c.close()

def push_agent_inbox(run_id,jid,kind,payload):
 iid=str(uuid.uuid4())
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_agent_inbox(id,job_id,orchestration_run_id,kind,payload_json,status,created_at) VALUES(?,?,?,?,?,'unread',?)",(iid,jid,run_id,kind,json.dumps(payload),now()));c.commit()
  finally:c.close()
 return iid

def save_context_summary(project_id,summary,source_count=1):
 sid=str(uuid.uuid4())
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_context_summaries(id,scope_type,scope_id,summary,source_count,created_at) VALUES(?,'project',?,?,?,?)",(sid,project_id,summary,int(source_count),now()));c.commit()
  finally:c.close()
 return sid

def mission_packet(item):
 c=connect()
 try:
  p=c.execute("SELECT p.*,o.title objective_title,o.description objective_description FROM org_projects p LEFT JOIN org_objectives o ON o.id=p.objective_id WHERE p.id=?",(item['project_id'],)).fetchone()
 finally:c.close()
 return {
  'objective_title':(p['objective_title'] if p and p['objective_title'] else 'Active ORQEVIA objective'),
  'objective_description':(p['objective_description'] if p and p['objective_description'] else ''),
  'project_title':(p['title'] if p else 'Internal project'),
 }

async def execute_orchestrated_job(run_id,item):
 route=choose_specialist(item['department'],item['title'],item['description'] or '')
 item=dict(item);item['route_reason']=route.reason
 packet=mission_packet(item)
 prior=orchestration_context(item['project_id'])
 evidence_context,evidence_meta=evidence_packet_for_specialist(route.specialist,item)
 brief=build_task_brief(objective_title=packet['objective_title'],objective_description=packet['objective_description'],project_title=packet['project_title'],department=item['department'],task_title=item['title'],task_description=item['description'] or '',specialist=route.specialist,context_summary=prior,evidence_context=evidence_context)
 jid=create_agent_job(run_id,item,route.specialist,brief,ORCH_MAX_ATTEMPTS)
 if route.specialist=='data' and not evidence_context:
  return mark_evidence_blocked(item,run_id,jid,"DATA_REQUIRED: no verified local CSV/JSON dataset exists in PRIME.",route.specialist)
 started=time.monotonic();attempts=0;retries=0;aid=None;feedback=''
 try:
  while attempts<ORCH_MAX_ATTEMPTS:
   attempts+=1;update_agent_job(jid,attempts=attempts,last_status=f'attempt {attempts} running')
   system=(BASE_SYSTEM+" You are the "+SPECIALISTS[route.specialist]['name']+" inside ORQEVIA's governed orchestration layer. Follow the mission brief exactly. You have no direct external authority.")
   d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':brief if attempts==1 else brief+f"\n\nSUPERVISOR REVISION REQUEST\n{feedback}\nRevise the deliverable; do not expand scope."}],'stream':False},900)
   content=d['message']['content'].strip()[:24000]
   if not aid:aid=create_artifact(item['task_id'],item['project_id'],run_id,item['title'],content)
   score,verdict,feedback,vsrc=await phase3_verify(item['title'],item['description'] or '',content,specialist=route.specialist,evidence_context=evidence_context)
   effective_verdict='pass' if verdict=='pass' and score>=PHASE3_VERIFY_THRESHOLD else 'revise'
   state,reason=supervisor_status(elapsed_seconds=time.monotonic()-started,attempts=attempts,max_attempts=ORCH_MAX_ATTEMPTS,score=score,verdict=effective_verdict)
   update_agent_job(jid,last_status=reason,result=content,artifact_id=aid)
   if state=='complete' and score>=PHASE3_VERIFY_THRESHOLD:
    update_artifact(aid,content,'verified',score,feedback)
    compact=compact_context(item['title'],content,score,feedback);save_context_summary(item['project_id'],compact,attempts)
    with WRITE_LOCK:
     c=connect()
     try:
      c.execute("UPDATE org_project_tasks SET status='completed',description=COALESCE(description,'')||?,updated_at=? WHERE id=?",('\n\nORCHESTRATED VERIFIED ARTIFACT '+aid+' SCORE '+str(round(score,1)),now(),item['task_id']))
      c.execute("UPDATE org_department_queue SET status='completed',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
     finally:c.close()
    update_agent_job(jid,status='completed',last_status=reason,result=content,artifact_id=aid,complete=True)
    push_agent_inbox(run_id,jid,'completed',{'task':item['title'],'specialist':route.specialist,'artifact_id':aid,'score':score,'verifier':vsrc})
    org_event('agent_job_completed','supervisor',jid,{'specialist':route.specialist,'score':score,'attempts':attempts})
    return {'job_id':jid,'task':item['title'],'specialist':route.specialist,'route_reason':route.reason,'status':'completed','artifact_id':aid,'score':score,'attempts':attempts,'retries':retries}
   if state=='retry':
    retries+=1;update_agent_job(jid,status='running',last_status=reason);continue
   update_artifact(aid,content,'needs_review',score,feedback)
   with WRITE_LOCK:
    c=connect()
    try:c.execute("UPDATE org_project_tasks SET status='review',updated_at=? WHERE id=?",(now(),item['task_id']));c.execute("UPDATE org_department_queue SET status='needs_review',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
    finally:c.close()
   approval_request('artifact_review',aid,'Review orchestration artifact below verification threshold',{'task_id':item['task_id'],'job_id':jid,'score':score,'feedback':feedback})
   update_agent_job(jid,status='needs_review',last_status=reason,result=content,artifact_id=aid,complete=True)
   push_agent_inbox(run_id,jid,'needs_review',{'task':item['title'],'specialist':route.specialist,'artifact_id':aid,'score':score,'feedback':feedback})
   return {'job_id':jid,'task':item['title'],'specialist':route.specialist,'route_reason':route.reason,'status':'needs_review','artifact_id':aid,'score':score,'attempts':attempts,'retries':retries}
 except Exception as e:
  state,reason=supervisor_status(elapsed_seconds=time.monotonic()-started,attempts=attempts,max_attempts=ORCH_MAX_ATTEMPTS,error=str(e))
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_project_tasks SET status='planned',updated_at=? WHERE id=?",(now(),item['task_id']));c.execute("UPDATE org_department_queue SET status='queued',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
   finally:c.close()
  update_agent_job(jid,status='failed',last_status=reason,result=str(e),complete=True)
  push_agent_inbox(run_id,jid,'failed',{'task':item['title'],'specialist':route.specialist,'error':str(e)[:2000]})
  watchdog_event('warning','orchestrated_job_failure',jid,{'task_id':item['task_id'],'error':str(e)})
  return {'job_id':jid,'task':item['title'],'specialist':route.specialist,'route_reason':route.reason,'status':'failed','error':str(e),'attempts':attempts,'retries':retries}

@app.get('/api/orchestration')
async def orchestration_state():
 c=connect()
 try:
  runs=[dict(r) for r in c.execute("SELECT * FROM org_orchestration_runs ORDER BY started_at DESC LIMIT 50")]
  jobs=[dict(r) for r in c.execute("SELECT * FROM org_agent_jobs ORDER BY started_at DESC LIMIT 100")]
  inbox=[dict(r) for r in c.execute("SELECT * FROM org_agent_inbox ORDER BY created_at DESC LIMIT 100")]
  context=[dict(r) for r in c.execute("SELECT * FROM org_context_summaries ORDER BY created_at DESC LIMIT 50")]
 finally:c.close()
 return {'specialists':SPECIALISTS,'counts':orchestration_counts(),'runs':runs,'jobs':jobs,'inbox':inbox,'context':context}

@app.post('/api/orchestration/inbox/drain')
async def drain_orchestration_inbox():
 with WRITE_LOCK:
  c=connect()
  try:
   rows=[dict(r) for r in c.execute("SELECT * FROM org_agent_inbox WHERE status='unread' ORDER BY created_at ASC LIMIT 100")]
   if rows:c.execute("UPDATE org_agent_inbox SET status='consumed',consumed_at=? WHERE status='unread'",(now(),));c.commit()
  finally:c.close()
 return {'consumed':len(rows),'items':rows}

@app.get('/api/orchestration/smoke')
async def orchestration_smoke():
 route=choose_specialist('Strategy','Map income opportunities','Create an internal economic opportunity portfolio and measurable priorities.')
 brief=build_task_brief(
  objective_title='Personal Economic Operating System',
  objective_description='Improve economic position through bounded internal analysis.',
  project_title='Orchestration smoke',
  department='Strategy',
  task_title='Map income opportunities',
  task_description='Create an internal economic opportunity portfolio and measurable priorities.',
  specialist=route.specialist,
  context_summary='',
  evidence_context=''
 )
 model_ok=False;content='';model_error=''
 try:
  d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':brief}],'stream':False},900)
  content=(d.get('message') or {}).get('content','').strip()
  model_ok=bool(content)
 except Exception as e:
  model_error=str(e)[:1200]

 safe_static="""Result
Create an internal opportunity inventory and rank options by expected upside, effort, reversibility and time-to-value.

Evidence actually used
No external/data evidence was used in this smoke test.

Assumptions and uncertainties
This is a structural smoke test, not a factual market analysis.

Recommended INTERNAL next step
Populate the opportunity inventory with verified evidence before making factual or quantitative claims."""
 guard_ok,guard_feedback=grounding_guard(safe_static,route.specialist,"")
 ok=(route.specialist=='strategy' and route.specialist in SPECIALISTS and len(brief)>200 and model_ok and guard_ok)
 return {
  'ok':ok,
  'route':route.specialist,
  'route_reason':route.reason,
  'brief_chars':len(brief),
  'content_chars':len(content),
  'model_ok':model_ok,
  'model_error':model_error,
  'grounding_guard_ok':guard_ok,
  'grounding_feedback':guard_feedback,
  'evaluator_source':'deterministic_smoke_guard'
 }

@app.get('/api/orchestration/grounding-smoke')
async def orchestration_grounding_smoke():
 fake="""Result: Review of 'Transaction History' database revealed users spend approximately $75 per week and grocery spending increased 13%."""
 ok1,reason1=grounding_guard(fake,"data","")
 good="""DATA_REQUIRED\nResult: No verified local dataset is available, so no spending calculation can be made.\nEvidence actually used: None.\nRecommended INTERNAL next step: Upload CSV/JSON transaction data."""
 ok2,reason2=grounding_guard(good,"strategy","")
 packet,ids=_dataset_evidence_packet()
 return {
  "ok":(not ok1) and ok2,
  "fabricated_claim_rejected":not ok1,
  "fabricated_reason":reason1,
  "honest_no_evidence_allowed":ok2,
  "dataset_count":len(ids),
  "data_without_dataset_would_block":len(ids)==0,
 }

@app.post('/api/orchestration/cycle')
async def orchestration_cycle():
 ok,reason=watchdog_can_run()
 if not ok:watchdog_event('warning','orchestration_cycle_blocked',None,{'reason':reason});raise HTTPException(429,'Watchdog blocked orchestration cycle: '+reason)
 run_id=str(uuid.uuid4());started=now()
 c=connect()
 try:
  objective=c.execute("SELECT id FROM org_objectives WHERE status='active' ORDER BY priority DESC,created_at ASC LIMIT 1").fetchone()
 finally:c.close()
 objective_id=objective['id'] if objective else None
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_orchestration_runs(id,objective_id,status,started_at,missions_planned,jobs_completed,jobs_retried,failures) VALUES(?,?,'running',?,0,0,0,0)",(run_id,objective_id,started));c.commit()
  finally:c.close()
 results=[];completed=retries=failures=blocked=planned=0;projects=set()
 try:
  for _ in range(ORCH_MAX_JOBS):
   item=select_next_queue_item()
   if not item:break
   planned+=1;projects.add(item['project_id'])
   with WRITE_LOCK:
    c=connect()
    try:c.execute("UPDATE org_department_queue SET status='leased',lease_until=?,updated_at=? WHERE id=?",((datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),now(),item['id']));c.execute("UPDATE org_project_tasks SET status='active',updated_at=? WHERE id=?",(now(),item['task_id']));c.commit()
    finally:c.close()
   r=await execute_orchestrated_job(run_id,item);results.append(r);retries+=int(r.get('retries',0))
   if r.get('status')=='completed':completed+=1
   elif r.get('status')=='blocked_evidence':
    blocked+=1
    break
   else:
    failures+=1
    if r.get('status') in {'failed','needs_review'}:break
  reviews=[]
  for pid in projects:
   rid=await phase3_review_project(pid)
   if rid:reviews.append(rid)
  status='completed' if failures==0 and blocked==0 else ('blocked_evidence' if blocked>0 and failures==0 else 'partial')
  summary={'jobs':results,'project_reviews':reviews,'blocked_evidence':blocked}
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_orchestration_runs SET status=?,completed_at=?,missions_planned=?,jobs_completed=?,jobs_retried=?,failures=?,summary=? WHERE id=?",(status,now(),planned,completed,retries,failures,json.dumps(summary),run_id));c.commit()
   finally:c.close()
  org_event('orchestration_cycle_completed','orchestrator',run_id,{'planned':planned,'completed':completed,'retries':retries,'failures':failures})
  return {'run_id':run_id,'status':status,'missions_planned':planned,'jobs_completed':completed,'jobs_retried':retries,'failures':failures,'blocked_evidence':blocked,'jobs':results,'project_reviews':reviews}
 except Exception as e:
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_orchestration_runs SET status='failed',completed_at=?,failures=failures+1,summary=? WHERE id=?",(now(),str(e),run_id));c.commit()
   finally:c.close()
  watchdog_event('critical','orchestration_cycle_crash',run_id,{'error':str(e)})
  raise

@app.get('/api/phase3/artifacts')
async def phase3_artifacts():
 c=connect()
 try:return [dict(r) for r in c.execute("SELECT a.*,t.title task_title,p.title project_title FROM org_artifacts a LEFT JOIN org_project_tasks t ON t.id=a.task_id LEFT JOIN org_projects p ON p.id=a.project_id ORDER BY a.created_at DESC LIMIT 200")]
 finally:c.close()

@app.get('/api/phase3/reviews')
async def phase3_reviews():
 c=connect()
 try:return [dict(r) for r in c.execute("SELECT * FROM org_project_reviews ORDER BY created_at DESC LIMIT 100")]
 finally:c.close()

@app.get('/api/phase3/approvals')
async def phase3_approvals():
 c=connect()
 try:return [dict(r) for r in c.execute("SELECT * FROM org_approval_requests ORDER BY created_at DESC LIMIT 100")]
 finally:c.close()

@app.post('/api/phase3/approvals/{rid}/approve')
async def phase3_approve(rid:str):
 with WRITE_LOCK:
  c=connect()
  try:
   r=c.execute("SELECT * FROM org_approval_requests WHERE id=?",(rid,)).fetchone()
   if not r:raise HTTPException(404,'Approval not found.')
   if r['status']!='pending':raise HTTPException(400,'Already resolved.')
   d=json.loads(r['details_json'] or '{}')
   if r['request_type']=='artifact_review':
    aid=r['subject_id']
    art=c.execute("SELECT * FROM org_artifacts WHERE id=?",(aid,)).fetchone()
    if not art:raise HTTPException(404,'Artifact not found.')
    c.execute("UPDATE org_artifacts SET verification_status='human_verified',verifier_feedback=COALESCE(verifier_feedback,'')||?,updated_at=? WHERE id=?",('\nHuman approved after review.',now(),aid))
    if art['task_id']:
     c.execute("UPDATE org_project_tasks SET status='completed',updated_at=? WHERE id=?",(now(),art['task_id']))
     c.execute("UPDATE org_department_queue SET status='completed',lease_until=NULL,updated_at=? WHERE task_id=?",(now(),art['task_id']))
   if r['request_type']=='followup_tasks':
    review=c.execute("SELECT * FROM org_project_reviews WHERE id=?",(r['subject_id'],)).fetchone()
    if not review:raise HTTPException(404,'Review not found.')
    pid=review['project_id'];seq=c.execute("SELECT COALESCE(MAX(sequence),0) FROM org_project_tasks WHERE project_id=?",(pid,)).fetchone()[0]
    for i,t in enumerate(d.get('tasks',[])[:3],1):
     c.execute("INSERT INTO org_project_tasks(id,project_id,title,description,status,sequence,created_at,updated_at) VALUES(?,?,?,?, 'planned',?,?,?)",(str(uuid.uuid4()),pid,str(t.get('title',''))[:300],str(t.get('description',''))[:5000],seq+i,now(),now()))
   c.execute("UPDATE org_approval_requests SET status='approved',resolved_at=? WHERE id=?",(now(),rid));c.commit()
  finally:c.close()
 org_event('phase3_approval_resolved','user',rid,{'decision':'approved'});return {'ok':True}

@app.post('/api/phase3/approvals/{rid}/reject')
async def phase3_reject(rid:str):
 with WRITE_LOCK:
  c=connect()
  try:
   r=c.execute("SELECT * FROM org_approval_requests WHERE id=?",(rid,)).fetchone()
   if not r:raise HTTPException(404,'Approval not found.')
   if r['status']!='pending':raise HTTPException(400,'Already resolved.')
   if r['request_type']=='artifact_review':
    art=c.execute("SELECT * FROM org_artifacts WHERE id=?",(r['subject_id'],)).fetchone()
    if art:
     c.execute("UPDATE org_artifacts SET verification_status='rejected',verifier_feedback=COALESCE(verifier_feedback,'')||?,updated_at=? WHERE id=?",('\nHuman rejected artifact.',now(),art['id']))
     if art['task_id']:
      c.execute("UPDATE org_project_tasks SET status='planned',updated_at=? WHERE id=?",(now(),art['task_id']))
      c.execute("UPDATE org_department_queue SET status='queued',available_at=?,lease_until=NULL,updated_at=? WHERE task_id=?",(now(),now(),art['task_id']))
   c.execute("UPDATE org_approval_requests SET status='rejected',resolved_at=? WHERE id=?",(now(),rid));c.commit()
  finally:c.close()
 return {'ok':True}

@app.get('/api/phase3/smoke')
async def phase3_smoke():
 d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':'Produce a concise three-point INTERNAL checklist for validating an AI task-execution system. No external actions.'}],'stream':False},900)
 content=d['message']['content'].strip();score,verdict,feedback,source=await phase3_verify("Phase 3 smoke test","Produce an internal validation checklist.",content)
 return {'ok':bool(content) and score>=30,'content_chars':len(content),'score':score,'verdict':verdict,'evaluator_source':source,'feedback':feedback}

@app.post('/api/phase3/verified-cycle')
async def phase3_verified_cycle():
 ok,reason=watchdog_can_run()
 if not ok:watchdog_event('warning','phase3_cycle_blocked',None,{'reason':reason});raise HTTPException(429,'Watchdog blocked Phase 3 cycle: '+reason)
 run_id=str(uuid.uuid4());started=now()
 with WRITE_LOCK:
  c=connect()
  try:c.execute("INSERT INTO org_autonomous_runs(id,status,started_at,cycles,tasks_created,tasks_completed,failures) VALUES(?,'running',?,0,0,0,0)",(run_id,started));c.commit()
  finally:c.close()
 completed=failures=cycles=0;summary=[];projects=set()
 try:
  for _ in range(max(1,min(PHASE3_MAX_TASKS_PER_RUN,3))):
   item=select_next_queue_item()
   if not item:break
   cycles+=1;task_id=item['task_id'];pid=item['project_id'];projects.add(pid)
   with WRITE_LOCK:
    c=connect()
    try:c.execute("UPDATE org_department_queue SET status='leased',lease_until=?,updated_at=? WHERE id=?",((datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),now(),item['id']));c.execute("UPDATE org_project_tasks SET status='active',updated_at=? WHERE id=?",(now(),task_id));c.commit()
    finally:c.close()
   try:
    legacy_route=choose_specialist(item['department'],item['title'],item['description'] or '')
    legacy_evidence,_legacy_meta=evidence_packet_for_specialist(legacy_route.specialist,item)
    if legacy_route.specialist=='data' and not legacy_evidence:
     content="DATA_REQUIRED: No verified local dataset is available. Upload CSV/JSON evidence in the Data tab before quantitative analysis."
     aid=create_artifact(task_id,pid,run_id,item['title'],content,'blocked_evidence',0,'DATA_REQUIRED')
     with WRITE_LOCK:
      c=connect()
      try:c.execute("UPDATE org_project_tasks SET status='blocked_evidence',updated_at=? WHERE id=?",(now(),task_id));c.execute("UPDATE org_department_queue SET status='blocked_evidence',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
      finally:c.close()
     summary.append({'task':item['title'],'status':'blocked_evidence','artifact_id':aid});break
    prompt=f"""You are ORQEVIA V7 Phase 3 executing one INTERNAL task.
Department: {item['department']}
Task: {item['title']}
Description: {item['description']}
Create a self-contained internal deliverable with: Result; Evidence/reasoning used; Recommended internal next step.
Do not invent evidence or perform external/consequential actions."""
    d=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':prompt}],'stream':False},900)
    content=d['message']['content'].strip()[:24000];aid=create_artifact(task_id,pid,run_id,item['title'],content)
    score,verdict,feedback,vsrc=await phase3_verify(item['title'],item['description'],content,specialist=legacy_route.specialist,evidence_context=legacy_evidence);rev=0
    while (verdict!='pass' or score<PHASE3_VERIFY_THRESHOLD) and rev<PHASE3_MAX_REVISIONS:
     rev+=1
     rd=await ollama_post('/api/chat',{'model':DEEP_MODEL,'messages':[{'role':'system','content':BASE_SYSTEM},{'role':'user','content':f"Revise this INTERNAL deliverable using feedback: {feedback}\\nTASK: {item['title']}\\nCURRENT:\\n{content[:16000]}"}],'stream':False},900)
     content=rd['message']['content'].strip()[:24000];score,verdict,feedback,vsrc=await phase3_verify(item['title'],item['description'],content,specialist=legacy_route.specialist,evidence_context=legacy_evidence)
    if verdict=='pass' and score>=PHASE3_VERIFY_THRESHOLD:
     update_artifact(aid,content,'verified',score,feedback)
     with WRITE_LOCK:
      c=connect()
      try:c.execute("UPDATE org_project_tasks SET status='completed',description=COALESCE(description,'')||?,updated_at=? WHERE id=?",('\\n\\nPHASE3 VERIFIED ARTIFACT '+aid+' SCORE '+str(round(score,1)),now(),task_id));c.execute("UPDATE org_department_queue SET status='completed',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
      finally:c.close()
     completed+=1;summary.append({'task':item['title'],'status':'completed','artifact_id':aid,'score':score,'verifier':vsrc})
    else:
     update_artifact(aid,content,'needs_review',score,feedback)
     with WRITE_LOCK:
      c=connect()
      try:c.execute("UPDATE org_project_tasks SET status='review',updated_at=? WHERE id=?",(now(),task_id));c.execute("UPDATE org_department_queue SET status='needs_review',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
      finally:c.close()
     approval_request('artifact_review',aid,'Review low-confidence Phase 3 artifact',{'task_id':task_id,'score':score,'feedback':feedback});failures+=1;summary.append({'task':item['title'],'status':'needs_review','artifact_id':aid,'score':score});break
   except Exception as e:
    failures+=1
    with WRITE_LOCK:
     c=connect()
     try:c.execute("UPDATE org_project_tasks SET status='planned',updated_at=? WHERE id=?",(now(),task_id));c.execute("UPDATE org_department_queue SET status='queued',lease_until=NULL,updated_at=? WHERE id=?",(now(),item['id']));c.commit()
     finally:c.close()
    watchdog_event('warning','phase3_task_failure',task_id,{'error':str(e)});summary.append({'task':item['title'],'status':'failed'});break
  reviews=[]
  for pid in projects:
   rid=await phase3_review_project(pid)
   if rid:reviews.append(rid)
  fs='completed' if failures==0 else 'partial'
  with WRITE_LOCK:
   c=connect()
   try:c.execute("UPDATE org_autonomous_runs SET status=?,completed_at=?,cycles=?,tasks_completed=?,failures=?,summary=? WHERE id=?",(fs,now(),cycles,completed,failures,json.dumps(summary),run_id));c.commit()
   finally:c.close()
  return {'run_id':run_id,'status':fs,'cycles':cycles,'tasks_completed':completed,'failures':failures,'summary':summary,'project_reviews':reviews}
 except Exception as e:
  watchdog_event('critical','phase3_cycle_crash',run_id,{'error':str(e)});raise


HTML=r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ORQEVIA V7 AUTONOMOUS ORGANIZATION — PHASE 3.1.1</title><style>
body{margin:0;background:#080b0f;color:#f5f7fb;font-family:Segoe UI,Arial}.w{max-width:1180px;margin:auto;padding:24px}.brand{font-size:38px;font-weight:800}.sub,.muted{color:#9eabba}.tabs{display:flex;gap:7px;flex-wrap:wrap;margin:18px 0}.tabs button,button,input,textarea,select{font:inherit;border:1px solid #334459;border-radius:10px;background:#0b1016;color:#f5f7fb;padding:10px}.c{background:#121821;border:1px solid #293646;border-radius:15px;padding:16px;margin:11px 0}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}.hidden{display:none}.good{color:#8ef0a3}.warn{color:#ffe08c}.primary{background:#f4f6f8;color:#111;font-weight:700}.danger{color:#ffbec7;border-color:#70404a}.msg{white-space:pre-wrap;line-height:1.5;margin:10px 0}textarea{width:100%;box-sizing:border-box;min-height:100px}input[type=text]{min-width:260px;flex:1}.metric{border:1px solid #293646;border-radius:12px;padding:12px}.metric b{display:block;font-size:20px}.line{padding:10px 0;border-bottom:1px solid #293646}.small{font-size:13px}pre{white-space:pre-wrap;max-height:420px;overflow:auto}
</style></head><body><div class="w"><div class="brand">ORQEVIA V7 AUTONOMOUS ORGANIZATION — PHASE 3.1.1</div><div class="sub">PRIME-native orchestration • evidence-grounded specialists • provenance gates • supervised retries • compacted verified context • approvals • closed loop retained</div><div class="tabs"><button onclick="tab('chat')">Chat</button><button onclick="tab('governance')">Governance</button><button onclick="tab('objectives')">Objectives</button><button onclick="tab('organization')">Organization</button><button onclick="tab('operations')">Operations</button><button onclick="tab('orchestration')">Orchestration</button><button onclick="tab('performance')">Performance</button><button onclick="tab('evidence')">Evidence</button><button onclick="tab('approvals')">Approvals</button><button onclick="tab('agents')">Agents</button><button onclick="tab('research')">Research</button><button onclick="tab('data')">Data</button><button onclick="tab('coding')">Coding</button><button onclick="tab('actions')">Actions</button><button onclick="tab('automation')">Automation</button><button onclick="tab('knowledge')">Knowledge</button><button onclick="tab('memory')">Memory</button><button onclick="tab('system')">System</button></div>
<section id="governance" class="hidden"><div class="c"><h3>Constitution</h3><div id="constitution"></div></div><div class="c"><h3>Authority grants</h3><div class="row"><select id="gscope"><option>internal_planning</option><option>internal_research</option><option>internal_data_analysis</option><option>internal_code_drafting</option><option>internal_document_creation</option></select><input id="gdesc" type="text" placeholder="Narrow authority description"><button onclick="grantAuthority()">Grant</button></div><div id="grants"></div></div><div class="c"><h3>Institutional event ledger</h3><div id="orgevents"></div></div></section><section id="objectives" class="hidden"><div class="c"><h3>Strategic objectives</h3><input id="otitle" type="text" placeholder="Objective title"><textarea id="odesc" placeholder="Objective description"></textarea><input id="opri" type="number" min="1" max="100" value="50"><button onclick="createObjective()">Create active objective</button></div><div class="c"><div id="objectivelist"></div></div></section><section id="organization" class="hidden"><div class="c"><h3>Bounded organization cycle</h3><p class="muted">Turns the highest-priority active objective into an internal draft project and planned tasks. Use Enqueue project to move planned tasks into Operations. External consequential actions remain prohibited.</p><button class="primary" onclick="orgCycle()">Run organization cycle</button><pre id="orgout"></pre></div><div class="c"><h3>Departments</h3><div id="departments"></div></div><div class="c"><h3>Projects and tasks</h3><div id="projects"></div></div></section><section id="operations" class="hidden"><div class="c"><h3>Persistent Operations</h3><p class="muted">Queue internal work, then run verified bounded cycles. Every completed task must produce a persisted artifact and pass evaluation. Completed projects enter the closed-loop review gate.</p><button class="primary" onclick="runAutonomy()">Run Phase 3 verified cycle</button><pre id="autonomyout"></pre></div><div class="c"><h3>Department Queue</h3><div id="queueview"></div></div><div class="c"><h3>Portfolios</h3><input id="pname" placeholder="Portfolio name"><textarea id="pdesc" placeholder="Portfolio description"></textarea><button onclick="createPortfolio()">Create portfolio</button><div id="portfolios"></div></div><div class="c"><h3>Recurring Internal Jobs</h3><input id="rname" placeholder="Job name"><select id="rscope"><option>internal_planning</option><option>internal_research</option><option>internal_data_analysis</option><option>internal_code_drafting</option><option>internal_document_creation</option></select><select id="rcadence"><option>hourly</option><option>daily</option></select><button onclick="createRecurring()">Create job</button><div id="recurring"></div></div></section>
<section id="orchestration" class="hidden"><div class="c"><h3>ORQEVIA Orchestration Layer</h3><p class="muted">One ORQEVIA voice routes queued internal missions to bounded specialists, supervises retries, verifies outputs, stores results in an async inbox, and compacts verified mission context. Existing governance and approval gates remain authoritative.</p><button class="primary" onclick="runOrchestration()">Run orchestrated cycle</button> <button onclick="drainInbox()">Drain completed-result inbox</button><pre id="orchout"></pre></div><div class="grid" id="orchmetrics"></div><div class="c"><h3>Specialist Jobs</h3><div id="orchjobs"></div></div><div class="c"><h3>Agent Inbox</h3><div id="orchinbox"></div></div><div class="c"><h3>Compacted Mission Context</h3><div id="orchcontext"></div></div></section>
<section id="performance" class="hidden"><div class="c"><h3>Performance & Watchdog</h3><div id="perfview"></div></div></section>
<section id="evidence" class="hidden"><div class="c"><h3>Evidence & Review</h3><p class="muted">Only <b>verified</b> or <b>human_verified</b> artifacts are trusted evidence. blocked_evidence, needs_review and rejected artifacts are not promoted into durable mission context.</p><div id="artifactview"></div></div><div class="c"><h3>Closed-loop Project Reviews</h3><div id="reviewview"></div></div></section><section id="approvals" class="hidden"><div class="c"><h3>Approval Gates</h3><div id="approvalview"></div></div></section><section id="chat"><div class="c"><b>Status:</b> <span id="st">checking…</span><span id="ct" class="muted"></span></div><div id="log" class="c"><div class="msg"><b>ORQEVIA:</b> Phase 3.1.1 evidence-grounded orchestration is running locally.</div></div><div class="c"><textarea id="q" placeholder="Ask PRIME..."></textarea><button class="primary" onclick="send()">Send</button> <label><input id="rem" type="checkbox" checked> Remember locally</label><span id="route" class="muted small"></span></div></section>
<section id="agents" class="hidden"><div class="grid" id="agentgrid"></div></section>
<section id="research" class="hidden"><div class="c"><h3>Research Agent</h3><input id="rq" type="text" placeholder="Research question"><textarea id="rurls" placeholder="Paste 1-5 public URLs, one per line"></textarea><button onclick="researchRun()">Research sources</button><pre id="rout"></pre></div></section>
<section id="data" class="hidden"><div class="c"><h3>Data Agent</h3><input id="dfile" type="file" accept=".csv,.json"><button onclick="dataUpload()">Upload dataset</button><div id="datasets"></div></div><div class="c"><input id="did" type="text" placeholder="Dataset ID"><input id="dq" type="text" placeholder="Question about dataset"><button onclick="dataAsk()">Ask Data Agent</button><pre id="dout"></pre></div></section>
<section id="coding" class="hidden"><div class="c"><h3>Coding Agent</h3><textarea id="creq" placeholder="Describe code you want..."></textarea><button onclick="codeGen()">Generate</button><pre id="cgen"></pre></div><div class="c"><textarea id="code" placeholder="Restricted Python code to validate/run"></textarea><button onclick="codeValidate()">Validate</button><button onclick="codeRun()">Run restricted Python</button><pre id="codeout"></pre><div class="row"><input id="cname" type="text" placeholder="script.py"><button onclick="proposeSaveCode()">Propose save</button></div></div></section>
<section id="actions" class="hidden"><div class="c"><h3>Approval Queue</h3><div id="alist"></div></div><div class="c"><h3>Propose private note</h3><input id="atitle" type="text" placeholder="Title"><textarea id="abody" placeholder="Note body"></textarea><button onclick="proposeNote()">Propose action</button></div></section>
<section id="automation" class="hidden"><div class="c"><h3>Automation Agent</h3><input id="autitle" type="text" placeholder="Title"><textarea id="auprompt" placeholder="Prompt to run"></textarea><select id="autype"><option value="once">Once</option><option value="hourly">Hourly</option><option value="daily">Daily</option></select><input id="aurun" type="text" placeholder="For once: 2026-08-09T02:00:00+00:00"><button onclick="autoCreate()">Create automation</button></div><div class="c"><div id="autos"></div></div></section>
<section id="knowledge" class="hidden"><div class="c"><input id="kfile" type="file"><button onclick="docUpload()">Index document</button><div id="docs"></div></div></section>
<section id="memory" class="hidden"><div class="c"><div id="facts"></div></div></section>
<section id="system" class="hidden"><div class="c"><button onclick="selftest()">Run self-test</button><pre id="test"></pre></div></section></div>
<script>
const E=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function tab(n){document.querySelectorAll('section').forEach(s=>s.classList.toggle('hidden',s.id!==n));if(n==='governance')loadGovernance();if(n==='objectives')loadObjectives();if(n==='organization')loadOrganization();if(n==='operations')loadOperations();if(n==='orchestration')loadOrchestration();if(n==='performance')loadPerformance();if(n==='agents')loadAgents();if(n==='data')loadData();if(n==='actions')loadActions();if(n==='automation')loadAutos();if(n==='knowledge')loadDocs();if(n==='memory')loadMem();if(n==='evidence')loadEvidence();if(n==='approvals')loadApprovals()}
async function status(){try{let d=await (await fetch('/api/status')).json();st.innerHTML=d.fast_ready&&d.memory_ready?'<span class="good">AI models ready</span>':'<span class="warn">Models preparing</span>';ct.textContent=` • facts ${d.facts} • memories ${d.memories} • datasets ${d.datasets} • actions ${d.pending_actions} • automations ${d.automations} • objectives ${d.objectives} • projects ${d.projects} • portfolios ${d.portfolios} • queued ${d.queued_tasks} • runs ${d.autonomous_runs} • artifacts ${d.artifacts} • verified ${d.verified_artifacts} • approvals ${d.pending_approvals} • orchestrations ${d.orchestration_runs} • agent jobs ${d.agent_jobs} • inbox ${d.agent_inbox}`}catch{st.textContent='status error'}}
async function send(){let m=q.value.trim();if(!m)return;q.value='';log.innerHTML+=`<div class="msg"><b>You:</b> ${E(m)}</div>`;let d=await (await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m,remember:rem.checked})})).json();log.innerHTML+=`<div class="msg"><b>ORQEVIA:</b> ${E(d.answer||d.detail)}</div>`;route.textContent=(d.agents||[]).join(' → ');status()}
async function loadAgents(){let d=await (await fetch('/api/agents')).json();agentgrid.innerHTML=Object.values(d.agents).map(a=>`<div class="metric"><b>${E(a.name)}</b><div>${E(a.purpose)}</div></div>`).join('')}
async function researchRun(){rout.textContent='Researching...';let urls=rurls.value.split(/\n+/).filter(Boolean);let r=await fetch('/api/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:rq.value,urls})});let d=await r.json();rout.textContent=d.answer||d.detail||JSON.stringify(d,null,2)}
async function dataUpload(){let f=dfile.files[0];if(!f)return;let fd=new FormData();fd.append('file',f);let d=await (await fetch('/api/datasets/upload',{method:'POST',body:fd})).json();alert(d.id?`Dataset ID: ${d.id}`:(d.detail||'failed'));loadData();status()}
async function loadData(){let d=await (await fetch('/api/datasets')).json();datasets.innerHTML=d.map(x=>`<div class="line"><b>${E(x.name)}</b> — ID ${E(x.id)} — ${x.row_count} rows</div>`).join('')||'<span class="muted">No datasets.</span>'}
async function dataAsk(){dout.textContent='Analyzing...';let d=await (await fetch('/api/datasets/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_id:did.value,question:dq.value})})).json();dout.textContent=d.answer||d.detail}
async function codeGen(){let d=await (await fetch('/api/code/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:creq.value,language:'python'})})).json();cgen.textContent=d.answer||d.detail}
async function codeValidate(){let d=await (await fetch('/api/code/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code.value})})).json();codeout.textContent=JSON.stringify(d,null,2)}
async function codeRun(){let d=await (await fetch('/api/code/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code.value})})).json();codeout.textContent=JSON.stringify(d,null,2)}
async function proposeSaveCode(){let d=await (await fetch('/api/actions/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action_type:'save_code_file',payload:{name:cname.value,code:code.value}})})).json();alert(d.id?'Queued for approval':d.detail);loadActions()}
async function proposeNote(){let d=await (await fetch('/api/actions/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action_type:'create_note',payload:{title:atitle.value,body:abody.value}})})).json();alert(d.id?'Queued for approval':d.detail);loadActions()}
async function loadActions(){let d=await (await fetch('/api/actions')).json();alist.innerHTML=d.map(x=>`<div class="line"><b>${E(x.action_type)}</b> — ${E(x.status)} ${x.status==='pending'?`<button onclick="approve('${x.id}')">Approve</button><button class="danger" onclick="rejectA('${x.id}')">Reject</button>`:''}</div>`).join('')||'<span class="muted">No actions.</span>';status()}
async function approve(id){let d=await (await fetch(`/api/actions/${id}/approve`,{method:'POST'})).json();alert(d.result||d.detail);loadActions()}
async function rejectA(id){await fetch(`/api/actions/${id}/reject`,{method:'POST'});loadActions()}
async function autoCreate(){let d=await (await fetch('/api/automations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:autitle.value,prompt:auprompt.value,schedule_type:autype.value,run_at:aurun.value||null,interval_hours:1})})).json();alert(d.id?'Automation created':d.detail);loadAutos();status()}
async function loadAutos(){let d=await (await fetch('/api/automations')).json();autos.innerHTML=d.automations.map(x=>`<div class="line"><b>${E(x.title)}</b> — ${E(x.schedule_type)} — next ${E(x.next_run_at)} — ${x.enabled?'enabled':'disabled'} <button onclick="toggleAuto('${x.id}')">Toggle</button></div>`).join('')||'<span class="muted">No automations.</span>'}
async function toggleAuto(id){await fetch(`/api/automations/${id}/toggle`,{method:'POST'});loadAutos();status()}
async function docUpload(){let f=kfile.files[0];if(!f)return;let fd=new FormData();fd.append('file',f);let d=await (await fetch('/api/documents/upload',{method:'POST',body:fd})).json();alert(d.id?'Indexed':d.detail);loadDocs();status()}
async function loadDocs(){let d=await (await fetch('/api/documents')).json();docs.innerHTML=d.map(x=>`<div class="line">${E(x.name)} — ${x.chunk_count} chunks</div>`).join('')||'<span class="muted">No documents.</span>'}
async function loadMem(){let d=await (await fetch('/api/memory')).json();facts.innerHTML=d.facts.map(x=>`<div class="line"><b>${E(x.key)}</b>: ${E(x.value)}</div>`).join('')||'<span class="muted">No facts.</span>'}
async function selftest(){test.textContent='Running...';let d=await (await fetch('/api/selftest')).json();test.textContent=JSON.stringify(d,null,2)}
async function loadGovernance(){let d=await (await fetch('/api/governance')).json();constitution.innerHTML=d.constitution.map(x=>`<div class="line"><b>${E(x.rule_key)}</b><div>${E(x.rule_text)}</div></div>`).join('');grants.innerHTML=d.authority_grants.map(x=>`<div class="line"><b>${E(x.scope)}</b> — ${E(x.status)} — ${E(x.description)} ${x.status==='active'?`<button class="danger" onclick="revokeAuthority('${x.id}')">Revoke</button>`:''}</div>`).join('')||'<span class="muted">No grants.</span>';orgevents.innerHTML=d.events.map(x=>`<div class="line"><b>${E(x.event_type)}</b> — ${E(x.actor)} — ${E(x.created_at)}</div>`).join('')||'<span class="muted">No events.</span>'}
async function grantAuthority(){let r=await fetch('/api/authority',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:gscope.value,description:gdesc.value})});let d=await r.json();if(!r.ok)alert(d.detail||'Failed');gdesc.value='';loadGovernance();status()}
async function revokeAuthority(id){await fetch(`/api/authority/${id}/revoke`,{method:'POST'});loadGovernance();status()}
async function createObjective(){let r=await fetch('/api/objectives',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:otitle.value,description:odesc.value,priority:Number(opri.value||50)})});let d=await r.json();if(!r.ok){alert(d.detail||'Failed');return}otitle.value='';odesc.value='';loadObjectives();status()}
async function loadObjectives(){let d=await (await fetch('/api/objectives')).json();objectivelist.innerHTML=d.map(x=>`<div class="line"><div><b>${E(x.title)}</b> — priority ${x.priority} — ${E(x.status)}<div class="muted small">${E(x.description)}</div></div>${x.status==='active'?`<button onclick="pauseObjective('${x.id}')">Pause</button>`:''}</div>`).join('')||'<span class="muted">No objectives.</span>'}
async function pauseObjective(id){await fetch(`/api/objectives/${id}/pause`,{method:'POST'});loadObjectives();status()}
async function orgCycle(){orgout.textContent='Executive Orchestrator is planning internally...';let r=await fetch('/api/org/cycle',{method:'POST'});let d=await r.json();orgout.textContent=r.ok?JSON.stringify(d,null,2):(d.detail||'Cycle failed');loadOrganization();status()}
async function loadOrganization(){let g=await (await fetch('/api/governance')).json();departments.innerHTML=g.departments.map(x=>`<div class="line"><b>${E(x.name)}</b><div>${E(x.mission)}</div></div>`).join('');let ps=await (await fetch('/api/projects')).json();projects.innerHTML=ps.map(p=>`<div class="c"><b>${E(p.title)}</b> — ${E(p.department)} — ${E(p.status)}<div>${E(p.description)}</div>${p.status==='draft'?`<div style="margin:12px 0"><button onclick="enqueueProject('${p.id}')">Enqueue project</button></div>`:''}${(p.tasks||[]).map(t=>`<div class="line">${t.sequence}. ${E(t.title)} — ${E(t.status)}</div>`).join('')}</div>`).join('')||'<span class="muted">No projects.</span>'}

async function enqueueProject(pid){
 if(!confirm("Queue this project\'s planned tasks for bounded autonomous execution?"))return;
 let r=await fetch(`/api/projects/${pid}/enqueue`,{method:'POST'});
 let d=await r.json();
 if(!r.ok){alert(d.detail||'Could not enqueue project.');return}
 alert(`Queued ${d.queued} task(s).`);
 await loadOrganization();
 await loadOperations();
 await status();
}

async function loadEvidence(){let a=await (await fetch('/api/phase3/artifacts')).json();artifactview.innerHTML=a.map(x=>`<div class="c"><b>${E(x.task_title||x.title)}</b> — <b>${E(x.verification_status)}</b> — score ${Number(x.quality_score||0).toFixed(1)}<div class="msg">${E((x.content||'').slice(0,3500))}</div><div class="small muted">${E(x.verifier_feedback||'')}</div></div>`).join('')||'<span class="muted">No Phase 3 artifacts yet.</span>';let r=await (await fetch('/api/phase3/reviews')).json();reviewview.innerHTML=r.map(x=>`<div class="c"><b>Project review</b> — score ${Number(x.score||0).toFixed(1)}<div class="msg">${E(x.summary)}</div></div>`).join('')||'<span class="muted">No project reviews yet.</span>'}
async function loadApprovals(){let a=await (await fetch('/api/phase3/approvals')).json();approvalview.innerHTML=a.map(x=>`<div class="c"><b>${E(x.title)}</b> — ${E(x.status)}<div class="small muted">${E(x.request_type||'')}</div>${x.status==='pending'?`<div><button onclick="resolveApproval('${x.id}','approve')">Approve</button> <button class="danger" onclick="resolveApproval('${x.id}','reject')">Reject</button></div>`:''}</div>`).join('')||'<span class="muted">No approvals.</span>'}
async function resolveApproval(id,d){let r=await fetch(`/api/phase3/approvals/${id}/${d}`,{method:'POST'});let x=await r.json();if(!r.ok){alert(x.detail||'Failed');return}loadApprovals();loadOrganization();status()}

async function createPortfolio(){let r=await fetch('/api/portfolios',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:pname.value,description:pdesc.value,priority:50})});let d=await r.json();if(!r.ok){alert(d.detail||'Failed');return}pname.value='';pdesc.value='';loadOperations();status()}
async function createRecurring(){let r=await fetch('/api/recurring-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:rname.value,scope:rscope.value,cadence:rcadence.value})});let d=await r.json();if(!r.ok){alert(d.detail||'Failed');return}rname.value='';loadOperations();status()}
async function runAutonomy(){autonomyout.textContent='Running Phase 3 verified cycle...';let r=await fetch('/api/phase3/verified-cycle',{method:'POST'});let d=await r.json();autonomyout.textContent=JSON.stringify(d,null,2);loadOperations();loadPerformance();loadEvidence();loadApprovals();status()}
async function loadOperations(){let q=await (await fetch('/api/queue')).json();queueview.innerHTML=q.map(x=>`<div class="line"><b>${E(x.department)}</b> — ${E(x.status)} — ${E(x.title)}</div>`).join('')||'<span class="muted">Queue empty.</span>';let p=await (await fetch('/api/portfolios')).json();portfolios.innerHTML=p.map(x=>`<div class="line"><b>${E(x.name)}</b> — ${E(x.status)}<div>${E(x.description)}</div></div>`).join('')||'<span class="muted">No portfolios.</span>';let r=await (await fetch('/api/recurring-jobs')).json();recurring.innerHTML=r.map(x=>`<div class="line"><b>${E(x.name)}</b> — ${E(x.scope)} — ${E(x.cadence)} — ${E(x.status)}</div>`).join('')||'<span class="muted">No recurring jobs.</span>'}
async function runOrchestration(){orchout.textContent='ORQEVIA Orchestrator is routing and supervising bounded specialist work...';let r=await fetch('/api/orchestration/cycle',{method:'POST'});let d=await r.json();orchout.textContent=r.ok?JSON.stringify(d,null,2):(d.detail||'Orchestration cycle failed');loadOrchestration();loadOperations();loadEvidence();loadApprovals();loadPerformance();status()}
async function drainInbox(){let r=await fetch('/api/orchestration/inbox/drain',{method:'POST'});let d=await r.json();orchout.textContent=JSON.stringify(d,null,2);loadOrchestration();status()}
async function loadOrchestration(){let d=await (await fetch('/api/orchestration')).json();let c=d.counts||{};orchmetrics.innerHTML=`<div class="metric"><b>${c.orchestration_runs||0}</b>orchestration runs</div><div class="metric"><b>${c.agent_jobs||0}</b>agent jobs</div><div class="metric"><b>${c.running_agent_jobs||0}</b>running jobs</div><div class="metric"><b>${c.agent_inbox||0}</b>unread results</div><div class="metric"><b>${c.context_summaries||0}</b>context summaries</div>`;orchjobs.innerHTML=(d.jobs||[]).map(x=>`<div class="line"><b>${E(x.specialist)}</b> — ${E(x.status)} — attempts ${x.attempts}/${x.max_attempts}<div>${E(x.last_status||'')}</div><div class="small muted">task ${E(x.task_id||'')}</div></div>`).join('')||'<span class="muted">No orchestrated jobs yet.</span>';orchinbox.innerHTML=(d.inbox||[]).map(x=>`<div class="line"><b>${E(x.kind)}</b> — ${E(x.status)} — ${E(x.created_at)}</div>`).join('')||'<span class="muted">Inbox empty.</span>';orchcontext.innerHTML=(d.context||[]).map(x=>`<div class="line"><div class="msg">${E(x.summary||'')}</div><div class="small muted">${E(x.scope_type)} ${E(x.scope_id)} • ${E(x.created_at)}</div></div>`).join('')||'<span class="muted">No compacted mission context yet.</span>'}
async function loadPerformance(){let d=await (await fetch('/api/performance')).json();perfview.innerHTML=`<h4>Autonomous runs</h4>${d.runs.map(x=>`<div class="line"><b>${E(x.status)}</b> — cycles ${x.cycles} — completed ${x.tasks_completed} — failures ${x.failures}</div>`).join('')||'<span class="muted">No runs.</span>'}<h4>Watchdog</h4>${d.watchdog.map(x=>`<div class="line"><b>${E(x.severity)}</b> — ${E(x.event_type)}</div>`).join('')||'<span class="muted">No watchdog events.</span>'}`}

status();
</script></body></html>"""
