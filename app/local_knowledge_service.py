"""Private loopback application service for the existing local AI environment."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime,timezone
import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path
import threading
import urllib.request
from urllib.parse import unquote
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import JSONResponse
from .local_knowledge import KnowledgeEngine,MAX_UPLOAD
from . import workspace_capabilities
from .observability import PRIVACY_FASTAPI_TELEMETRY, install_observability

ROOT=Path(os.environ.get('ORQEVIA_LOCAL_AI_ROOT',str(Path.home()/'orqevia-ai')))
from .postgres_intelligence import knowledge_engine
ENGINE=knowledge_engine(ROOT)
SLOT=threading.BoundedSemaphore(1)

@asynccontextmanager
async def lifespan(app):
    # Load only the existing offline embedding model; no model download/pull.
    try:await asyncio.to_thread(ENGINE._embed,['ORQEVIA readiness'])
    except Exception:ENGINE.last_error='EMBEDDING_INITIALIZATION_FAILED'
    yield

app=FastAPI(title='ORQEVIA local knowledge',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan,
    telemetry=PRIVACY_FASTAPI_TELEMETRY)
OBSERVABILITY=install_observability(app)

def audit(action,phase,status=None):
    root=ROOT/'operations';root.mkdir(parents=True,exist_ok=True)
    with (root/'workspace-knowledge-audit.jsonl').open('a',encoding='utf8') as f:
        f.write(json.dumps({'at_utc':datetime.now(timezone.utc).isoformat(),'action':action,'phase':phase,'status':status})+'\n');f.flush()

@app.middleware('http')
async def boundary(request,call_next):
    token=os.getenv('ORQEVIA_SERVICE_TOKEN','')
    supplied=request.headers.getlist('authorization')
    if len(token)<16 or len(supplied)!=1 or not hmac.compare_digest(supplied[0],'Bearer '+token):return JSONResponse({'detail':'Service authentication required'},status_code=401)
    expected=os.getenv('ORQEVIA_OWNER_ACCOUNT','')
    principal=request.headers.get('x-orqevia-owner','')
    if not expected or not hmac.compare_digest(principal,hashlib.sha256(expected.encode()).hexdigest()):return JSONResponse({'detail':'Owner scope unavailable'},status_code=403)
    if request.method=='POST':
        try:
            async def body():
                parts=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>MAX_UPLOAD:raise ValueError()
                    parts.append(chunk)
                return b''.join(parts)
            request._body=await asyncio.wait_for(body(),10)
        except (ValueError,TimeoutError):return JSONResponse({'detail':'Request bound exceeded'},status_code=413)
    response=await call_next(request)
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

def operation(action,call):
    if not SLOT.acquire(blocking=False):raise HTTPException(429,'Local intelligence is processing another request; retry shortly')
    try:
        audit(action,'started')
        result=call();audit(action,'completed',200);return result
    except HTTPException:raise
    except ValueError as e:
        audit(action,'completed',422);raise HTTPException(422,str(e)) from None
    except (OSError,RuntimeError,ImportError,KeyError,subprocess.TimeoutExpired) as e:
        try:audit(action,'completed',503)
        except OSError:pass
        raise HTTPException(503,'Local intelligence dependency unavailable; existing documents preserved') from None
    finally:SLOT.release()

@app.get('/health')
def health():
    state=ENGINE.health()
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/tags',timeout=3) as r:models=json.load(r).get('models',[])
        model=next((m for m in models if m.get('name')=='qwen2.5:7b'),None)
        state['generation']={'status':'MODEL_INSTALLED' if model else 'MODEL_UNAVAILABLE','model':'qwen2.5:7b','digest':model.get('digest') if model else None}
    except (OSError,ValueError):state['generation']={'status':'UNAVAILABLE'}
    state['initialization_error']=ENGINE.last_error
    state['source_revision']=os.getenv('ORQEVIA_LOCAL_RELEASE','UNVERIFIED')
    return state

@app.get('/documents')
def documents():return operation('documents.read',ENGINE.list_documents)

@app.get('/workspace')
def workspace():return workspace_capabilities.workspace_status(ROOT)

@app.get('/ideas')
def ideas():return workspace_capabilities.ideas(ROOT)

@app.post('/ideas')
async def save_idea(request:Request):
    try:
        value=json.loads(await request.body())
        audit('ideas.save','started');result=workspace_capabilities.ideas(ROOT,value);audit('ideas.save','completed',200)
        return result
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid bounded idea') from None
    except OSError:raise HTTPException(503,'Idea storage unavailable') from None

@app.post('/scaffold')
async def scaffold(request:Request):
    try:value=json.loads(await request.body())
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid scaffold request') from None
    return await asyncio.to_thread(operation,'workspace.scaffold',lambda:workspace_capabilities.scaffold(value))

@app.post('/validate')
async def validate():return await asyncio.to_thread(operation,'workspace.validate',lambda:workspace_capabilities.validate_local_pipeline(ROOT))

@app.post('/ingest')
async def ingest(request:Request):
    name=unquote(request.headers.get('x-document-name',''))
    raw=await request.body()
    return await asyncio.to_thread(operation,'documents.ingest',lambda:ENGINE.ingest(name,raw))

@app.post('/reindex')
def reindex():return operation('documents.reindex',ENGINE.reindex)

async def arguments(request):
    try:
        raw=await request.body()
        if len(raw)>16000:raise ValueError()
        value=json.loads(raw)
        if not isinstance(value,dict) or 'question' not in value or set(value)-{'question','top_k','document_ids','observations'}:raise ValueError()
        return value
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid bounded knowledge request') from None

@app.post('/retrieve')
async def retrieve(request:Request):
    value=await arguments(request)
    if 'observations' in value:raise HTTPException(422,'Observation context is available only to the answer adapter')
    return await asyncio.to_thread(operation,'knowledge.retrieve',lambda:ENGINE.retrieve(**value))

@app.post('/answer')
async def answer(request:Request):
    value=await arguments(request)
    return await asyncio.to_thread(operation,'knowledge.answer',lambda:ENGINE.answer(**value))
