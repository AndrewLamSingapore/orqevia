"""Bounded browser sessions over the existing Interface Node authority boundary."""
import hashlib
import logging
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import unquote,urlsplit
import uuid

from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE='__Host-JARVIS-PWA'
DEVICE_COOKIE='__Host-JARVIS-Device'
SCOPES=['identity.read','health.read','objective.submit','task.read','task.cancel','artifact.read']
OWNER_SCOPES=[*SCOPES,'authority.owner.verify']
SESSION_SECONDS=8*3600
DEVICE_SECONDS=90*24*3600
router=APIRouter(prefix='/pwa/api',tags=['pwa-session'])
owner_router=APIRouter(prefix='/pwa/owner',tags=['local-pairing'])

def clock():return time.time()

def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def database():
    root=Path(os.getenv('PRIME_DATA_DIR','/data'));root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'pwa-sessions.db',timeout=15)
    db.execute('BEGIN IMMEDIATE')
    db.execute('CREATE TABLE IF NOT EXISTS pairing(code_hash TEXT PRIMARY KEY,expires REAL NOT NULL,used INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS sessions(session_hash TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS devices(device_hash TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,expires REAL NOT NULL,revoked INTEGER NOT NULL DEFAULT 0,owner_account_id TEXT,role TEXT NOT NULL DEFAULT \'MEMBER\')')
    db.execute('CREATE TABLE IF NOT EXISTS admission(peer_hash TEXT,bucket INTEGER,count INTEGER,PRIMARY KEY(peer_hash,bucket))')
    for table in ('pairing','sessions'):
        if 'owner_account_id' not in {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute('ALTER TABLE '+table+' ADD COLUMN owner_account_id TEXT')
        if 'role' not in {r[1] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute("ALTER TABLE "+table+" ADD COLUMN role TEXT NOT NULL DEFAULT 'MEMBER'")
    db.commit();return db

def internal_token(client):
    key=os.getenv('PRIME_SPINE_TOKEN','')
    if len(key)<16:raise HTTPException(503,'PWA authority unavailable')
    return hmac.new(key.encode(),('jarvis-pwa-client-v1:'+client).encode(),hashlib.sha256).hexdigest()

def client_policy(client):
    if not re.fullmatch(r'pwa:[a-f0-9]{32}',client or ''):return {}
    with database() as db:row=db.execute('SELECT expires,revoked,owner_account_id,role FROM sessions WHERE client_id=?',(client,)).fetchone()
    if not row or row[1] or row[0]<=time.time():return {}
    # Browser identity grants only the existing bounded server-owned client policy.
    classification=os.getenv('PRIME_PWA_DATA_CLASSIFICATION','LOCAL_ONLY')
    try:ceiling=float(os.getenv('PRIME_PWA_MAX_COST_USD','0'))
    except ValueError:raise HTTPException(503,'PWA policy unavailable') from None
    if classification not in {'LOCAL_ONLY','CLOUD_PERMITTED'} or not math.isfinite(ceiling) or not 0<=ceiling<=1:raise HTTPException(503,'PWA policy unavailable')
    if row[3] not in {'OWNER','MEMBER'}:raise HTTPException(503,'PWA role unavailable')
    capabilities=OWNER_SCOPES if row[3]=='OWNER' else SCOPES
    return {'token_sha256':digest(internal_token(client)),'expires_at':row[0],'capabilities':capabilities,'role':row[3],
            'data_classification':classification,'max_cost_usd':ceiling,
            **({'owner_account_id':row[2]} if row[2] else {})}

def session_state(request):
    cookie=request.cookies.get(COOKIE,'')
    if not cookie:return 'MISSING',None
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',cookie):return 'INVALID',None
    with database() as db:row=db.execute('SELECT client_id,expires,revoked,role,owner_account_id FROM sessions WHERE session_hash=?',(digest(cookie),)).fetchone()
    if not row:return 'INVALID',None
    value={'clientId':row[0],'expiresAt':row[1],'role':row[3],'ownerAccountId':row[4]}
    if row[2]:return 'REVOKED',value
    if row[1]<=time.time():return 'EXPIRED',value
    if row[3] not in {'OWNER','MEMBER'}:return 'INVALID',None
    return 'VALID',value

def session(request):
    state,value=session_state(request)
    return value if state=='VALID' else None

def device_state(request):
    raw=request.cookies.get(DEVICE_COOKIE,'')
    if not raw:return 'MISSING',None
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}',raw):return 'INVALID',None
    with database() as db:row=db.execute('SELECT client_id,expires,revoked,owner_account_id,role FROM devices WHERE device_hash=?',(digest(raw),)).fetchone()
    if not row:return 'INVALID',None
    if row[2]:return 'REVOKED',None
    if row[1]<=time.time():return 'EXPIRED',None
    if row[4] not in {'OWNER','MEMBER'}:return 'INVALID',None
    return 'VALID',{'clientId':row[0],'deviceExpiresAt':row[1],'ownerAccountId':row[3],'role':row[4]}

def device(request):return device_state(request)[1]

def access_mode():
    """Owner directive 2026-10-16: default to one-tap, code-free access.

    'open'    - the session endpoint admits this browser without any code.
    'pairing' - the historical pairing-code trust gate.
    Unknown values fail closed to 'pairing'."""
    mode=os.getenv('PRIME_PWA_ACCESS_MODE','open').strip().lower()
    return mode if mode in {'open','pairing'} else 'pairing'

def _auto_admit(request):
    """Issue a durable session without any pairing code (open access mode).

    Reached only through the same origin-validated /pwa routes as every other
    session action. Role and owner binding stay bounded by configuration."""
    now=clock();raw=secrets.token_urlsafe(32);device_raw=secrets.token_urlsafe(32);client='pwa:'+uuid.uuid4().hex
    role=os.getenv('PRIME_PWA_AUTO_ROLE','OWNER').strip().upper()
    if role not in {'OWNER','MEMBER'}:raise HTTPException(503,'PWA role unavailable')
    account=os.getenv('PRIME_PWA_OWNER_ACCOUNT_ID') or None
    if account is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}',account):raise HTTPException(503,'Owner account unavailable')
    internal_token(client)
    with database() as db:
        db.execute('INSERT INTO sessions(session_hash,client_id,expires,revoked,owner_account_id,role) VALUES(?,?,?,0,?,?)',(digest(raw),client,now+SESSION_SECONDS,account,role))
        db.execute('INSERT INTO devices VALUES(?,?,?,0,?,?)',(digest(device_raw),client,now+DEVICE_SECONDS,account,role))
    return raw,device_raw,{'clientId':client,'expiresAt':now+SESSION_SECONDS,'role':role,'ownerAccountId':account}

def _cookies(response,session_token,device_token=None):
    if session_token:response.set_cookie(COOKIE,session_token,max_age=SESSION_SECONDS,httponly=True,secure=True,samesite='strict',path='/')
    if device_token:response.set_cookie(DEVICE_COOKIE,device_token,max_age=DEVICE_SECONDS,httponly=True,secure=True,samesite='strict',path='/')
    return response

def _issue_device(current):
    raw=secrets.token_urlsafe(32);expires=clock()+DEVICE_SECONDS
    with database() as db:
        row=db.execute('SELECT owner_account_id,role FROM sessions WHERE client_id=?',(current['clientId'],)).fetchone()
        existing=db.execute('SELECT 1 FROM devices WHERE client_id=?',(current['clientId'],)).fetchone()
        if not row or existing:return None
        db.execute('INSERT INTO devices VALUES(?,?,?,0,?,?)',(digest(raw),current['clientId'],expires,row[0],row[1]))
    return raw

def _refresh_session(bound):
    raw=secrets.token_urlsafe(32);expires=clock()+SESSION_SECONDS;internal_token(bound['clientId'])
    with database() as db:
        changed=db.execute('UPDATE sessions SET session_hash=?,expires=?,owner_account_id=?,role=? WHERE client_id=? AND revoked=0',
            (digest(raw),expires,bound['ownerAccountId'],bound['role'],bound['clientId'])).rowcount
        if changed!=1:return None
    return raw,{'clientId':bound['clientId'],'expiresAt':expires,'role':bound['role']}

def require_session(request):
    value=session(request)
    if not value:raise HTTPException(401,'Session unavailable')
    return value

def safe_shell_navigation(request):
    """Allow only an unauthenticated top-level browser handoff to the PWA shell."""
    return (request.method=='GET'
            and request.url.path in {'/pwa/','/pwa/index.html'}
            and request.headers.get('origin') is None
            and request.headers.get('sec-fetch-mode')=='navigate'
            # A service-worker/browser handoff may preserve navigate mode but
            # present an empty destination. Only the public shell is admitted.
            and request.headers.get('sec-fetch-dest') in {'document','empty'})

def pwa_origins():
    primary=os.getenv('PRIME_PWA_ORIGIN','').rstrip('/')
    try:parsed=urlsplit(primary)
    except ValueError:return ()
    if parsed.scheme!='https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:return ()
    additional=os.getenv('PRIME_PWA_ADDITIONAL_ORIGINS','')
    # The public hostname is an explicit, single-origin opt-in, not a general host allowlist.
    if additional not in {'','https://jarvis.lamjarvis.com'}:return ()
    return (primary,additional) if additional else (primary,)


def origin_valid(request,write=False):
    expected=str(request.base_url).rstrip('/')
    if request.url.scheme!='https' or expected not in pwa_origins():return False
    origin=request.headers.get('origin')
    if origin is not None and origin!=expected:return False
    site=request.headers.get('sec-fetch-site')
    if site in {'cross-site','same-site'} and not (not write and safe_shell_navigation(request)):return False
    return not write or (origin==expected and request.headers.get('x-jarvis-pwa')=='1')

async def bounded_body(request,limit):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>limit:raise HTTPException(413,'Content too large')
    return bytes(raw)

@owner_router.post('/pairing')
async def pairing(request:Request):
    from .client_auth import authenticate_owner
    if not request.client or request.client.host not in {'127.0.0.1','::1'}:raise HTTPException(403,'Local owner interaction required')
    authenticate_owner(request.headers.get('authorization'))
    expected=os.getenv('PRIME_PWA_OWNER_ORIGIN','http://127.0.0.1:8000').rstrip('/')
    parsed=urlsplit(expected)
    if parsed.hostname not in {'127.0.0.1','::1','localhost'} or parsed.scheme not in {'http','https'} or parsed.path or parsed.username:raise HTTPException(503,'Local owner origin unavailable')
    if str(request.base_url).rstrip('/')!=expected or request.headers.get('origin')!=expected or request.headers.get('x-jarvis-pwa')!='1':raise HTTPException(403,'Origin rejected')
    account=os.getenv('PRIME_PWA_OWNER_ACCOUNT_ID') or None
    if account is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}',account):raise HTTPException(503,'Owner account unavailable')
    raw_body=await bounded_body(request,256)
    try:body=json.loads(raw_body) if raw_body else {}
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid pairing request') from None
    if not isinstance(body,dict) or set(body)-{'role'} or body.get('role','MEMBER') not in {'OWNER','MEMBER'}:
        raise HTTPException(422,'Invalid pairing request')
    role=body.get('role','MEMBER')
    code=secrets.token_urlsafe(16);expires=time.time()+300
    with database() as db:db.execute('INSERT INTO pairing(code_hash,expires,used,owner_account_id,role) VALUES(?,?,0,?,?)',(digest(code),expires,account,role))
    # Intentionally returned only to authenticated local interactive owner UI.
    return JSONResponse({'code':code,'expiresAt':expires,'role':role},headers={'Cache-Control':'no-store'})

@router.get('/session')
def get_session(request:Request):
    session_status,current=session_state(request)
    device_status,bound=device_state(request)
    device_token=None;session_token=None;clear_credentials=False
    if session_status in {'INVALID','REVOKED'}:
        current=None;clear_credentials=True
    elif current and bound and any(current[key]!=bound[key] for key in ('clientId','role','ownerAccountId')):
        current=None;clear_credentials=True
    elif session_status=='VALID' and device_status=='MISSING':device_token=_issue_device(current)
    elif session_status=='VALID' and device_status!='VALID':current=None;clear_credentials=True
    elif session_status in {'MISSING','EXPIRED'} and bound:
        if current and any(current[key]!=bound[key] for key in ('clientId','role','ownerAccountId')):
            current=None;clear_credentials=True
        else:
            refreshed=_refresh_session(bound)
            if refreshed:session_token,current=refreshed
    elif session_status!='VALID':
        current=None
    if not current and access_mode()=='open':
        try:
            session_token,device_token,current=_auto_admit(request)
            clear_credentials=False
        except HTTPException:
            current=None
    if current and bound and not session_token and current['expiresAt']-clock()<SESSION_SECONDS/2:
        # Extend the same opaque credential. Normal active use must not rotate
        # cookies across tabs or require enrollment every eight hours.
        expires=min(clock()+SESSION_SECONDS,bound['deviceExpiresAt'])
        with database() as db:
            changed=db.execute('UPDATE sessions SET expires=? WHERE session_hash=? AND revoked=0',
                (expires,digest(request.cookies.get(COOKIE,'')))).rowcount
        if changed:
            session_token=request.cookies[COOKIE];current['expiresAt']=expires
    recovery=None if current else ('DEVICE_REVOKED' if device_status=='REVOKED' else
        'DEVICE_EXPIRED' if device_status=='EXPIRED' else 'TRUST_REQUIRED')
    response=JSONResponse({'protocol':'jarvis.interface.v1','authenticated':bool(current),
        'recovery':recovery,**(current or {})},headers={'Cache-Control':'no-store'})
    if clear_credentials:
        response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict')
        response.delete_cookie(DEVICE_COOKIE,path='/',secure=True,httponly=True,samesite='strict')
        return response
    return _cookies(response,session_token,device_token) if session_token or device_token else response

@router.post('/enroll')
async def enroll(request:Request):
    try:body=json.loads(await bounded_body(request,2048))
    except (ValueError,UnicodeError):raise HTTPException(422,'Invalid enrollment') from None
    if not isinstance(body,dict) or set(body)!={'code'} or not isinstance(body['code'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{22}',body['code']):raise HTTPException(422,'Invalid enrollment')
    now=clock();peer=digest(request.client.host if request.client else 'unknown');bucket=int(now//60)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM admission WHERE bucket<?',(bucket-2,))
        db.execute('INSERT INTO admission VALUES(?,?,1) ON CONFLICT(peer_hash,bucket) DO UPDATE SET count=count+1',(peer,bucket))
        # Count the adjacent bucket as well so a client cannot double its
        # allowance by placing attempts on both sides of a minute boundary.
        # This intentionally fails closed for up to one additional bucket.
        count=db.execute('SELECT COALESCE(SUM(count),0) FROM admission WHERE peer_hash=? AND bucket>=?',
                         (peer,bucket-1)).fetchone()[0]
        db.commit()
        if count>10:raise HTTPException(429,'Enrollment rate limited')
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT expires,used,owner_account_id,role FROM pairing WHERE code_hash=?',(digest(body['code']),)).fetchone()
        if not row or row[1] or row[0]<=now:raise HTTPException(401,'Enrollment unavailable')
        raw=secrets.token_urlsafe(32);device_raw=secrets.token_urlsafe(32);client='pwa:'+uuid.uuid4().hex;expires=now+SESSION_SECONDS
        internal_token(client)
        db.execute('UPDATE pairing SET used=1 WHERE code_hash=?',(digest(body['code']),))
        db.execute('INSERT INTO sessions(session_hash,client_id,expires,revoked,owner_account_id,role) VALUES(?,?,?,0,?,?)',(digest(raw),client,expires,row[2],row[3]))
        db.execute('INSERT INTO devices VALUES(?,?,?,0,?,?)',(digest(device_raw),client,now+DEVICE_SECONDS,row[2],row[3]))
    response=JSONResponse({'authenticated':True,'clientId':client,'expiresAt':expires,'role':row[3]})
    return _cookies(response,raw,device_raw)

@router.post('/logout')
def logout(request:Request):
    raw=request.cookies.get(COOKIE,'')
    device_raw=request.cookies.get(DEVICE_COOKIE,'')
    with database() as db:
        db.execute('UPDATE sessions SET revoked=1 WHERE session_hash=?',(digest(raw),))
        db.execute('UPDATE devices SET revoked=1 WHERE device_hash=?',(digest(device_raw),))
    response=JSONResponse({'authenticated':False});response.delete_cookie(COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    response.delete_cookie(DEVICE_COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    return response

@router.post('/owner-authority-check')
def owner_authority_check(request:Request):
    """Side-effect-free proof that current authority is enforced by PRIME."""
    current=require_session(request)
    if current['role']!='OWNER':raise HTTPException(403,'Owner authority required')
    return {'authorized':True,'role':'OWNER','capability':'authority.owner.verify'}

@router.post('/uploads')
async def upload(request:Request):
    from .artifact_factory import ArtifactFactory
    from . import interface_node as node
    current=require_session(request)
    filename=unquote(request.headers.get('x-filename',''))
    if not filename or len(filename)>128 or '/' in filename or '\\' in filename or any(ord(c)<32 for c in filename):raise HTTPException(422,'Invalid filename')
    suffix=Path(filename).suffix.lower()
    if suffix not in {'.json','.txt','.md'}:raise HTTPException(415,'Only UTF-8 JSON, text and Markdown supported')
    raw=await bounded_body(request,1024*1024)
    try:text=raw.decode('utf-8')
    except UnicodeError:raise HTTPException(415,'UTF-8 required') from None
    task='upload-'+uuid.uuid4().hex;factory=ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR','/data'))/'artifacts')
    try:meta=factory.create(kind='json' if suffix=='.json' else 'markdown',content=text,task_id=task,creator=current['clientId'],provenance='Client-provided untrusted upload')
    except ValueError:raise HTTPException(422,'Upload validation failed') from None
    with node.db_connect() as db:
        node.account_binding(db,current['clientId'],current_required=True)
        db.execute('INSERT INTO requests VALUES(?,?,?,?)',(current['clientId'],task,hashlib.sha256(raw).hexdigest(),task))
    return {'artifactId':meta['artifact_id'],'sha256':meta['sha256'],'bytes':meta['bytes'],'reference':'artifact:'+meta['artifact_id']}

class PWASessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        path=request.url.path
        is_pwa=path.startswith('/pwa/') and not path.startswith('/pwa/owner/')
        cookie_client=path.startswith('/interface/v1') and COOKIE in request.cookies
        if is_pwa or cookie_client:
            try:
                if not origin_valid(request,request.method not in {'GET','HEAD'}):
                    logging.getLogger(__name__).warning(
                        'PWA origin rejected transport=%s configured_host=%s origin_match=%s fetch=%s/%s/%s',
                        request.url.scheme,str(request.base_url).rstrip('/') in pwa_origins(),
                        request.headers.get('origin') in {None,str(request.base_url).rstrip('/')},
                        request.headers.get('sec-fetch-site','missing'),
                        request.headers.get('sec-fetch-mode','missing'),
                        request.headers.get('sec-fetch-dest','missing'))
                    raise HTTPException(403,'Origin rejected')
                if request.method=='OPTIONS':raise HTTPException(405,'Method unavailable')
                if cookie_client:
                    if any(x in request.headers for x in ('authorization','x-client-id','x-jarvis-client-id')):raise HTTPException(400,'Caller identity headers forbidden')
                    current=require_session(request);client=current['clientId']
                    headers=list(request.scope['headers'])
                    headers.extend([(b'authorization',('Bearer '+internal_token(client)).encode()),(b'x-jarvis-client-id',client.encode())])
                    request.scope['headers']=headers
                    if request.method=='POST' and path=='/interface/v1/objectives':
                        body=json.loads(await bounded_body(request,128*1024))
                        refs=body.pop('uploaded_artifact_ids',[])
                        if not isinstance(refs,list) or len(refs)>4 or any(not isinstance(x,str) or not re.fullmatch('[a-f0-9]{32}',x) for x in refs):raise HTTPException(422,'Invalid upload references')
                        if refs:
                            from .artifact_factory import ArtifactFactory
                            from . import interface_node as node
                            factory=ArtifactFactory(Path(os.getenv('PRIME_DATA_DIR','/data'))/'artifacts')
                            context=body.get('context','')
                            if not isinstance(context,str):raise HTTPException(422,'Invalid context')
                            for ref in refs:
                                meta,raw=factory.retrieve(ref);node.own_task(meta['task_id'],client)
                                context+='\nUntrusted uploaded evidence '+ref+':\n'+raw.decode('utf-8')
                            if len(context)>80000:raise HTTPException(422,'Uploaded evidence exceeds context limit')
                            body['context']=context
                        request._body=json.dumps(body).encode()
                        request.scope['headers']=[(k,v) for k,v in request.scope['headers'] if k!=b'content-length']+[(b'content-length',str(len(request._body)).encode())]
                response=await call_next(request)
            except HTTPException as exc:response=JSONResponse({'error':{'code':'PWA_REQUEST_REJECTED'}},status_code=exc.status_code)
            except (ValueError,UnicodeError,KeyError,FileNotFoundError,TypeError,AttributeError):response=JSONResponse({'error':{'code':'PWA_REQUEST_REJECTED'}},status_code=422)
            response.headers['Cache-Control']='no-store'
            response.headers['Referrer-Policy']='no-referrer'
            response.headers['X-Content-Type-Options']='nosniff'
            response.headers['Content-Security-Policy']="default-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            return response
        return await call_next(request)
