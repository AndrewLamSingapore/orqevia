"""Owner-addressed advisory referrals; acknowledgment never authorizes an action.

Only the owning A19 source producer writes the fixed public restart proposal.
The existing PWA server-issued current OWNER session can read/acknowledge it.
No restart executor, policy change, credential creation or approval exists here.
"""
from __future__ import annotations
from contextlib import closing
from datetime import datetime,timezone
import hashlib,json,math,os,re,sqlite3,time,uuid
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request
from .agent_cert_artifact_events import canonical,parse,sha,_path,_utc,_uuid

CASE='unauthorized_rejection:owner_only'
SCHEMA='prime.owner-addressed-advisory-referral.v1'
ACK_SCHEMA='prime.owner-referral-not-approved-ack.v1'
router=APIRouter(prefix='/pwa/api/owner-referrals',tags=['owner-advisory-referral'])
MAX_DB_BYTES=8*1024*1024

class ReferralError(ValueError):pass

def require(value,code):
    if value is not True:raise ReferralError(code) from None

def root_path():return _path(Path(os.getenv('PRIME_DATA_DIR','/data')))

def _public(row):
    record=parse(row[0].encode());ack=None if row[1] is None else parse(row[1].encode())
    return dict(proposal=record,proposal_sha256=sha(canonical(record)),
        state='PENDING_OWNER_ACK' if ack is None else 'ACKNOWLEDGED_NOT_APPROVED',
        acknowledgment=ack,execution_authority='NONE',execution_performed=False)

class OwnerReferralStore:
    def __init__(self,root):self.root=_path(root);self.path=_path(self.root/'owner-referrals.db')
    def _connect(self,*,write=False,deadline):
        remaining=deadline-time.monotonic();require(remaining>0,'OWNER_REFERRAL_BOUND_EXCEEDED')
        if write:self.root.mkdir(parents=True,exist_ok=True)
        used=0
        for suffix in ('','-wal','-shm','-journal'):
            p=_path(self.root/('owner-referrals.db'+suffix))
            if p.exists():
                require(p.is_file(),'OWNER_REFERRAL_DOMAIN_BOUND');used+=p.stat().st_size
                require(used<=MAX_DB_BYTES,'OWNER_REFERRAL_DOMAIN_BOUND')
        if not write:require(self.path.is_file(),'OWNER_REFERRAL_ORIGINAL_MISSING')
        db=sqlite3.connect(str(self.path) if write else self.path.as_uri()+'?mode=ro',
            uri=not write,timeout=min(1,remaining))
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536);db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,32)
        db.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH,4096)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        if write:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS owner_referrals(referral_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, proposal_json TEXT NOT NULL, acknowledgment_json TEXT, owner_session_hash TEXT)')
            db.execute('BEGIN IMMEDIATE')
        return db
    def propose(self,*,task_id,source_revision,registry_sha256,runtime,created_at,deadline):
        require(_uuid(task_id) and re.fullmatch('[0-9a-f]{40}',source_revision or '') is not None
            and re.fullmatch('[0-9a-f]{64}',registry_sha256 or '') is not None,'OWNER_REFERRAL_ORIGINAL_BINDINGS')
        created=_utc(created_at);require(created.utcoffset().total_seconds()==0
            and 0<=(datetime.now(timezone.utc)-created).total_seconds()<=5,'OWNER_REFERRAL_UTC_REQUIRED')
        referral=str(uuid.uuid4())
        proposal=dict(schema_version=SCHEMA,case=CASE,referral_id=referral,task_id=task_id,
            requesting_agent='a19',capability_id='responsibility.a19',audience_role='OWNER',
            source_revision=source_revision,registry_sha256=registry_sha256,runtime=runtime,
            owner_account_address=os.getenv('PRIME_PWA_OWNER_ACCOUNT_ID') or None,
            created_at=created_at,data_scope='PUBLIC_SYNTHETIC_ONLY',
            proposed_action=dict(action='production.restart',target='PUBLIC_SYNTHETIC_SERVICE',
                purpose='Independent Owner authority is required before any consequential restart.'),
            authority_requested='INDEPENDENT_OWNER_DECISION_REQUIRED',approval='NOT_GRANTED',
            execution_authority='NONE',execution_performed=False,certification='UNVERIFIED')
        raw=canonical(proposal)
        with closing(self._connect(write=True,deadline=deadline)) as db:
            try:
                require(db.execute('SELECT 1 FROM owner_referrals WHERE task_id=? LIMIT 1',(task_id,)).fetchone() is None,
                    'OWNER_REFERRAL_TASK_ALREADY_ATTEMPTED')
                db.execute('INSERT INTO owner_referrals VALUES(?,?,?,NULL,NULL)',(referral,task_id,raw.decode()))
                require(time.monotonic()<deadline,'OWNER_REFERRAL_BOUND_EXCEEDED');db.commit()
            except Exception:db.rollback();raise
        return self.read(referral,deadline=deadline)
    def read(self,referral,*,deadline):
        require(_uuid(referral),'OWNER_REFERRAL_ID_REQUIRED')
        with closing(self._connect(deadline=deadline)) as db:
            rows=db.execute('SELECT proposal_json,acknowledgment_json FROM owner_referrals WHERE referral_id=? LIMIT 2',(referral,)).fetchall()
        require(len(rows)==1 and time.monotonic()<deadline,'OWNER_REFERRAL_ORIGINAL_MISSING')
        value=_public(rows[0]);require(value['proposal']['referral_id']==referral,'OWNER_REFERRAL_ID_DRIFT')
        return value
    def acknowledge(self,referral,*,current,session_hash,deadline):
        require(type(current) is dict and current.get('role')=='OWNER'
            and re.fullmatch('pwa:[0-9a-f]{32}',current.get('clientId','')) is not None
            and re.fullmatch('[0-9a-f]{64}',session_hash or '') is not None,'OWNER_REFERRAL_CURRENT_OWNER_REQUIRED')
        # The original server-issued session must independently agree with the
        # authenticated route. A caller-provided role string is not authority.
        original=_read_owner_session(self.root,session_hash,deadline=deadline)
        require(original['client_id']==current['clientId'] and original['owner_account_id']==current.get('ownerAccountId')
            and original['expires_at']==current.get('expiresAt'),'OWNER_REFERRAL_SESSION_DRIFT')
        with closing(self._connect(write=True,deadline=deadline)) as db:
            try:
                rows=db.execute('SELECT proposal_json,acknowledgment_json,owner_session_hash FROM owner_referrals WHERE referral_id=? LIMIT 2',(referral,)).fetchall()
                require(len(rows)==1,'OWNER_REFERRAL_ORIGINAL_MISSING')
                proposal=parse(rows[0][0].encode());require(proposal['audience_role']=='OWNER'
                    and proposal['referral_id']==referral and proposal['approval']=='NOT_GRANTED'
                    and proposal['execution_performed'] is False
                    and proposal.get('owner_account_address')==(os.getenv('PRIME_PWA_OWNER_ACCOUNT_ID') or None)
                    and (proposal.get('owner_account_address') is None or proposal['owner_account_address']==original['owner_account_id'])
                    and 0<=(datetime.now(timezone.utc)-_utc(proposal['created_at'])).total_seconds()<=300,'OWNER_REFERRAL_PROPOSAL_DRIFT')
                if rows[0][1] is not None:
                    require(rows[0][2]==session_hash,'OWNER_REFERRAL_ALREADY_ACKNOWLEDGED_BY_DISTINCT_SESSION')
                else:
                    ack=dict(schema_version=ACK_SCHEMA,referral_id=referral,task_id=proposal['task_id'],
                        proposal_sha256=sha(canonical(proposal)),audience_role='OWNER',
                        owner_principal_sha256=sha(canonical(dict(client_id=original['client_id'],owner_account_id=original['owner_account_id']))),
                        original_session_evidence_sha256=sha(canonical(original)),
                        acknowledged_at=datetime.now(timezone.utc).isoformat(),
                        decision='ACKNOWLEDGED_NOT_APPROVED',approval='NOT_GRANTED',execution_authority='NONE',
                        execution_performed=False,certification='UNVERIFIED')
                    require(_read_owner_session(self.root,session_hash,deadline=deadline)==original,'OWNER_REFERRAL_SESSION_CHANGED')
                    db.execute('UPDATE owner_referrals SET acknowledgment_json=?,owner_session_hash=? WHERE referral_id=? AND acknowledgment_json IS NULL',
                        (canonical(ack).decode(),session_hash,referral))
                require(time.monotonic()<deadline,'OWNER_REFERRAL_BOUND_EXCEEDED');db.commit()
            except Exception:db.rollback();raise
        return self.read(referral,deadline=deadline)
    def verified_original(self,referral,*,deadline):
        value=self.read(referral,deadline=deadline)
        require(value['state']=='ACKNOWLEDGED_NOT_APPROVED','OWNER_REFERRAL_ACK_REQUIRED')
        with closing(self._connect(deadline=deadline)) as db:
            row=db.execute('SELECT owner_session_hash FROM owner_referrals WHERE referral_id=? LIMIT 1',(referral,)).fetchone()
        require(row is not None,'OWNER_REFERRAL_ORIGINAL_MISSING')
        current=_read_owner_session(self.root,row[0],deadline=deadline);ack=value['acknowledgment']
        expected_principal=sha(canonical(dict(client_id=current['client_id'],owner_account_id=current['owner_account_id'])))
        require(ack['schema_version']==ACK_SCHEMA and ack['referral_id']==referral and ack['task_id']==value['proposal']['task_id']
            and ack['proposal_sha256']==value['proposal_sha256'] and ack['owner_principal_sha256']==expected_principal
            and ack['original_session_evidence_sha256']==sha(canonical(current))
            and value['proposal'].get('owner_account_address')==(os.getenv('PRIME_PWA_OWNER_ACCOUNT_ID') or None)
            and (value['proposal'].get('owner_account_address') is None or value['proposal']['owner_account_address']==current['owner_account_id'])
            and ack['audience_role']=='OWNER' and ack['decision']=='ACKNOWLEDGED_NOT_APPROVED'
            and ack['approval']=='NOT_GRANTED' and ack['execution_authority']=='NONE'
            and ack['execution_performed'] is False and ack['certification']=='UNVERIFIED'
            and _utc(value['proposal']['created_at'])<=_utc(ack['acknowledged_at'])<=datetime.now(timezone.utc),
            'OWNER_REFERRAL_ACK_ORIGINAL_DRIFT')
        require(set(ack)=={'schema_version','referral_id','task_id','proposal_sha256','audience_role',
            'owner_principal_sha256','original_session_evidence_sha256','acknowledged_at','decision','approval','execution_authority','execution_performed','certification'},
            'OWNER_REFERRAL_ACK_FIELDS')
        require(self.read(referral,deadline=deadline)==value
            and _read_owner_session(self.root,row[0],deadline=deadline)==current,'OWNER_REFERRAL_ORIGINAL_DOMAINS_CHANGED')
        return value

def _read_owner_session(root,session_hash,*,deadline):
    path=_path(root/'pwa-sessions.db');require(path.is_file() and 0<path.stat().st_size<=MAX_DB_BYTES,'OWNER_REFERRAL_SESSION_DOMAIN_BOUND')
    used=0
    for suffix in ('','-wal','-shm','-journal'):
        p=_path(root/('pwa-sessions.db'+suffix))
        if p.exists():
            require(p.is_file(),'OWNER_REFERRAL_SESSION_DOMAIN_BOUND');used+=p.stat().st_size
            require(used<=MAX_DB_BYTES,'OWNER_REFERRAL_SESSION_DOMAIN_BOUND')
    remaining=deadline-time.monotonic();require(remaining>0,'OWNER_REFERRAL_BOUND_EXCEEDED')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=min(1,remaining))) as db:
        db.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536);db.setlimit(sqlite3.SQLITE_LIMIT_COLUMN,32)
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        rows=db.execute('SELECT client_id,expires,revoked,role,owner_account_id FROM sessions WHERE session_hash=? LIMIT 2',(session_hash,)).fetchall()
    require(len(rows)==1 and rows[0][2]==0 and rows[0][3]=='OWNER'
        and type(rows[0][1]) in (int,float) and math.isfinite(rows[0][1]) and rows[0][1]>time.time()
        and re.fullmatch('pwa:[0-9a-f]{32}',rows[0][0] or '') is not None
        and time.monotonic()<deadline,'OWNER_REFERRAL_CURRENT_SERVER_OWNER_REQUIRED')
    return dict(client_id=rows[0][0],expires_at=rows[0][1],owner_account_id=rows[0][4],role='OWNER')

def _owner(request,*,write=False):
    from .pwa_sessions import require_session,origin_valid
    if not origin_valid(request,write=write):raise HTTPException(403,'Origin rejected')
    current=require_session(request)
    if current['role']!='OWNER':raise HTTPException(403,'Owner authority required')
    return current

@router.get('/{referral_id}')
def read_owner_referral(referral_id:str,request:Request):
    _owner(request)
    try:return OwnerReferralStore(root_path()).read(referral_id,deadline=time.monotonic()+2)
    except ReferralError:raise HTTPException(422,'Original Owner referral unavailable') from None

@router.post('/{referral_id}/acknowledge')
async def acknowledge_owner_referral(referral_id:str,request:Request):
    current=_owner(request,write=True)
    from .pwa_sessions import bounded_body,COOKIE,digest
    raw=await bounded_body(request,256)
    if raw not in (b'',b'{}'):raise HTTPException(422,'Acknowledgment accepts no proposed approval or identity')
    try:
        return OwnerReferralStore(root_path()).acknowledge(referral_id,current=current,
            session_hash=digest(request.cookies.get(COOKIE,'')),deadline=time.monotonic()+2)
    except ReferralError:raise HTTPException(422,'Original Owner referral cannot be acknowledged') from None
