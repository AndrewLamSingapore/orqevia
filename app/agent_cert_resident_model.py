from contextlib import closing
"""Prospective source-only resident admission; never a certified model response.

No API mount or production default. A separate reviewed source qualification
root supplies its existing native queue and action ledger. Residency is an
observation under the native lease, not an atomic no-cold-load guarantee.
"""
from dataclasses import dataclass,field
from datetime import datetime,timezone,timedelta
from pathlib import Path
import asyncio,hashlib,json,math,os,re,sqlite3,time
from urllib.parse import urlsplit

CASE='model_substitution:complete'
SCHEMA='prime.source-residency-admission.v1'
MAX_PS=65536

class ResidencyAdmissionError(PermissionError):pass
class ResidencyUnavailable(ResidencyAdmissionError):
    def __init__(self,receipt):
        super().__init__('RESIDENCY_UNAVAILABLE');self._receipt_bytes=canonical(receipt)
    @property
    def receipt(self):return json.loads(self._receipt_bytes)
class ResidencyLostAfterDispatch(ResidencyAdmissionError):
    def __init__(self,receipt):
        super().__init__('RESIDENCY_LOST_AFTER_DISPATCH');self._receipt_bytes=canonical(receipt)
    @property
    def receipt(self):return json.loads(self._receipt_bytes)

def require(value,code):
    if value is not True:raise ResidencyAdmissionError(code) from None

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def utc(value):
    require(type(value) is str and len(value)<=64,'RESIDENCY_UTC_REQUIRED')
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:raise ResidencyAdmissionError('RESIDENCY_UTC_REQUIRED') from None
    require(parsed.tzinfo is not None,'RESIDENCY_UTC_REQUIRED');return parsed.astimezone(timezone.utc)
def now():return datetime.now(timezone.utc)
def parse(raw):
    require(type(raw) is bytes and 0<len(raw)<=MAX_PS,'RESIDENCY_RESPONSE_BOUND')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'RESIDENCY_DUPLICATE_JSON_KEY');result[key]=value
        return result
    try:return json.loads(raw.decode(),object_pairs_hook=pairs,parse_constant=lambda _:require(False,'RESIDENCY_JSON_CONSTANT'))
    except ResidencyAdmissionError:raise
    except Exception:raise ResidencyAdmissionError('RESIDENCY_JSON_REQUIRED') from None

@dataclass(frozen=True)
class ResidentCaseWindow:
    """Source-owned original five seconds; no caller supplied duration/reset."""
    started:datetime=field(default_factory=now,init=False)
    monotonic_started:float=field(default_factory=time.monotonic,init=False)
    deadline:datetime=field(init=False)
    def __post_init__(self):object.__setattr__(self,'deadline',self.started+timedelta(seconds=5))
    @classmethod
    def from_original_task(cls,*,root,task_id,submitted_request,runtime,dispatch_window):
        """Internal dispatcher seam: only narrow its existing clock anchors.

        Caller-supplied HTTP fields cannot supply this exact source-owned window.
        The native Objective read verifies the original request/runtime and its
        creation time before any assessment claim or inference mutation.
        """
        require(type(dispatch_window) is cls,'RESIDENCY_ORIGINAL_DISPATCH_WINDOW_REQUIRED')
        from .agent_cert_fresh_input import read_task
        remaining=dispatch_window.remaining()
        original=read_task(root,task_id,submitted_request,runtime,
            deadline=time.monotonic()+min(1,remaining))
        created=utc(original['created_at'])
        require(created<=now() and original['task_id']==task_id,'RESIDENCY_ORIGINAL_TASK_CLOCK_REQUIRED')
        result=object.__new__(cls)
        object.__setattr__(result,'started',min(dispatch_window.started,created))
        object.__setattr__(result,'monotonic_started',dispatch_window.monotonic_started)
        object.__setattr__(result,'deadline',min(dispatch_window.deadline,created+timedelta(seconds=5)))
        result.remaining();return result
    def remaining(self):
        elapsed=time.monotonic()-self.monotonic_started
        require(math.isfinite(elapsed) and elapsed>=0,'RESIDENCY_MONOTONIC_INVALID')
        left=min(5-elapsed,(self.deadline-now()).total_seconds(),5)
        require(math.isfinite(left) and left>0,'RESIDENCY_SHARED_DEADLINE_EXHAUSTED');return left

@dataclass(frozen=True)
class ResidentAdmissionContract:
    source_revision:str
    domain_id:str
    domain_root:Path
    prompt_sha256:str
    fast_model:str
    deep_model:str
    fast_digest:str
    deep_digest:str
    registry_sha256:str
    window:ResidentCaseWindow
    generation_binding:str='{}'
    _chat_raw:bytearray=field(default_factory=bytearray,init=False,repr=False,compare=False)
    _chat_request_raw:bytearray=field(default_factory=bytearray,init=False,repr=False,compare=False)
    def __post_init__(self):
        require(re.fullmatch('[0-9a-f]{40}',self.source_revision or '') is not None,'RESIDENCY_SOURCE_REQUIRED')
        require(re.fullmatch('[0-9a-f-]{36}',self.domain_id or '') is not None,'RESIDENCY_SOURCE_DOMAIN_REQUIRED')
        require(type(self.domain_root) is Path or isinstance(self.domain_root,Path),'RESIDENCY_SOURCE_ROOT_REQUIRED')
        require(type(self.window) is ResidentCaseWindow,'RESIDENCY_SOURCE_WINDOW_REQUIRED')
        require(self.fast_model=='gemma3:1b' and self.deep_model=='gemma3:4b','RESIDENCY_GOLDEN_ROLES_REQUIRED')
        require(all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) is not None
            for v in (self.prompt_sha256,self.fast_digest,self.deep_digest,self.registry_sha256)),'RESIDENCY_IMMUTABLE_PINS_REQUIRED')
    @property
    def binding(self):
        return dict(schema=SCHEMA,case=CASE,source_revision=self.source_revision,domain_id=self.domain_id,registry_sha256=self.registry_sha256,
            identity_scope='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME',prompt_sha256=self.prompt_sha256,
            alternatives=[dict(role='fast',model=self.fast_model,tier='NANO',digest=self.fast_digest),
                dict(role='deep',model=self.deep_model,tier='MINI',digest=self.deep_digest)],
            minimum_tier='NANO',data_classification='LOCAL_ONLY',max_cost_usd=0,max_retries=0,
            residency_policy='resident_admission_observation',requested_cold_loads=0,
            started_at=self.window.started.isoformat(),deadline=self.window.deadline.isoformat(),
            generation=parse(self.generation_binding.encode()),
            qualification='SOURCE_UNREADY')
    def source_domain(self):
        require(self.domain_root.is_absolute(),'RESIDENCY_SOURCE_ROOT_REQUIRED')
        def parents():
            identities=[]
            for parent in (self.domain_root,*self.domain_root.parents):
                require(not parent.is_symlink() and not parent.is_junction(),'RESIDENCY_REPARSE_ROOT_FORBIDDEN')
                info=parent.lstat();identities.append((str(parent),info.st_dev,info.st_ino,info.st_mode))
            return identities
        before=parents();root=self.domain_root.resolve(strict=True);db=root/'compute-queue.db'
        marker=root/'source-qualification-domain.json'
        require(marker.is_file() and not marker.is_symlink() and not marker.is_junction(),
            'RESIDENCY_SOURCE_DOMAIN_REQUIRED')
        def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_mode)
        original=marker.lstat();require(original.st_size<=4096,'RESIDENCY_SOURCE_MARKER_BOUND')
        with marker.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            require(identity(opened)==identity(original),'RESIDENCY_SOURCE_MARKER_IDENTITY_DRIFT')
            raw=stream.read(4097)
            require(len(raw)<=4096 and identity(os.fstat(stream.fileno()))==identity(original),
                'RESIDENCY_SOURCE_MARKER_BOUND_OR_DRIFT')
        require(not marker.is_symlink() and not marker.is_junction()
            and identity(marker.lstat())==identity(original) and parents()==before
            and self.domain_root.resolve(strict=True)==root,'RESIDENCY_SOURCE_MARKER_PATH_DRIFT')
        require(parse(raw)==dict(schema='prime.source-qualification-domain.v1',
            domain_id=self.domain_id,source_revision=self.source_revision,scope='SOURCE_TEMPORARY_DOMAIN_NOT_ACCEPTED_RUNTIME'),
            'RESIDENCY_SOURCE_DOMAIN_DRIFT')
        return db
    def native_row(self,job):
        db=self.source_domain()
        require(job.get('_admission_db')==str(db) and db.is_file(),'RESIDENCY_ORIGINAL_STORE_REQUIRED')
        size=0
        for suffix in ('','-wal','-shm','-journal'):
            file=Path(str(db)+suffix)
            require(not file.is_symlink() and not file.is_junction(),'RESIDENCY_NATIVE_REPARSE_FORBIDDEN')
            if file.exists():
                require(file.is_file(),'RESIDENCY_NATIVE_FILE_REQUIRED');size+=file.stat().st_size
        require(size<=8*1024*1024,'RESIDENCY_NATIVE_STORE_BOUND')
        deadline=time.monotonic()+min(1,self.window.remaining())
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=min(1,self.window.remaining()))) as connection:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536)
            connection.set_progress_handler(lambda:1 if time.monotonic()>=deadline else 0,100)
            row=connection.execute('SELECT agent,prompt,model,model_role,provider,status,attempts,max_retries,max_cost_usd,allow_cloud,external_execution,data_classification,classification,timeout_seconds,preferred_provider,ram_mb,vram_mb FROM compute_jobs WHERE id=?',(job['id'],)).fetchone()
        require(time.monotonic()<deadline and row is not None,'RESIDENCY_ORIGINAL_STORE_REQUIRED')
        expected=(job['agent'],job['prompt'],job['model'],job['model_role'],job['provider'],'running',1,0,0.0,0,0,'LOCAL_ONLY','R0',5,job['provider'],1024,0)
        require(row==expected,'RESIDENCY_ORIGINAL_JOB_DRIFT')
        self.window.remaining();return row
    def bind(self,job,provider,settings):
        require(job.get('agent')=='a19' and sha(job.get('prompt','').encode())==self.prompt_sha256,
            'RESIDENCY_ORIGINAL_ACTOR_PROMPT_REQUIRED')
        from .agent_cert_artifact_events import _registry
        _registry(self.registry_sha256)
        from .agent_registry import canonical_agent_id
        require(canonical_agent_id(job['agent'])=='a19','RESIDENCY_CURRENT_REGISTRY_REQUIRED')
        require(settings.fast_model==self.fast_model and settings.deep_model==self.deep_model,
            'RESIDENCY_CONFIGURED_ROLE_DRIFT')
        require(provider.kind=='local' and provider.model in (self.fast_model,self.deep_model)
            and provider.name==('ollama-fast' if provider.model==self.fast_model else 'ollama-deep')
            and job.get('model')==provider.model and job.get('provider')==provider.name
            and job.get('model_role')==('fast' if provider.model==self.fast_model else 'deep'),
            'RESIDENCY_ORDERED_LOCAL_ALTERNATIVE_REQUIRED')
        try:endpoint=urlsplit(settings.ollama_base_url)
        except ValueError:raise ResidencyAdmissionError('RESIDENCY_FIXED_LOOPBACK_ENDPOINT_REQUIRED') from None
        require(endpoint.scheme=='http' and endpoint.hostname=='127.0.0.1' and endpoint.username is None
            and endpoint.password is None and not endpoint.path and not endpoint.query and not endpoint.fragment
            and endpoint.port is not None and 1<=endpoint.port<=65535,'RESIDENCY_FIXED_LOOPBACK_ENDPOINT_REQUIRED')
        self.native_row(job)
    def validate_ps(self,raw,model,job_id):
        body=parse(raw);require(type(body) is dict and set(body)=={'models'} and type(body['models']) is list
            and len(body['models'])<=8,'RESIDENCY_NATIVE_MODELS_REQUIRED')
        models={}
        for value in body['models']:
            require(type(value) is dict and type(value.get('name')) is str and value['name']==value.get('model')
                and len(value['name'])<=128 and value['name'] not in models,'RESIDENCY_NATIVE_MODEL_BINDING_REQUIRED')
            require(type(value.get('digest')) is str and re.fullmatch('[0-9a-f]{64}',value['digest']) is not None,
                'RESIDENCY_NATIVE_DIGEST_REQUIRED')
            utc(value.get('expires_at'));models[value['name']]=value
        selected=models.get(model);reason='NOT_RESIDENT' if selected is None else 'EXPIRY_BEFORE_SHARED_DEADLINE'
        if selected is not None:
            require(selected['digest']==(self.fast_digest if model==self.fast_model else self.deep_digest),
                'RESIDENCY_NATIVE_DIGEST_DRIFT')
        available=selected is not None and utc(selected['expires_at'])>=self.window.deadline
        receipt=dict(schema=SCHEMA,contract_sha256=sha(canonical(self.binding)),job_id=job_id,model=model,
            source_revision=self.source_revision,domain_id=self.domain_id,raw_ps_utf8=raw.decode(),raw_ps_sha256=sha(raw),
            observed_at=now().isoformat(),expires_at=None if selected is None else selected['expires_at'],
            decision='RESIDENT_ADMITTED' if available else 'RESIDENCY_UNAVAILABLE',reason=None if available else reason,
            qualification='SOURCE_UNREADY',atomic_no_cold_load_guarantee=False)
        self.window.remaining()
        if not available:raise ResidencyUnavailable(receipt)
        return receipt
    async def observe(self,job,provider,settings,lease_check,*,phase):
        import httpx
        require(phase in ('PRE_DISPATCH','POST_DISPATCH'),'RESIDENCY_OBSERVATION_PHASE_REQUIRED')
        self.bind(job,provider,settings);lease_check();self.window.remaining()
        async with httpx.AsyncClient(timeout=min(1,self.window.remaining())) as client:
            async with client.stream('GET',settings.ollama_base_url+'/api/ps',headers={'Accept-Encoding':'identity'}) as response:
                require(response.status_code==200 and response.headers.get('content-encoding','identity')=='identity',
                    'RESIDENCY_NATIVE_READ_FAILED')
                raw=bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    self.window.remaining();require(len(raw)+len(chunk)<=MAX_PS,'RESIDENCY_RESPONSE_BOUND');raw.extend(chunk)
        lease_check();self.native_row(job)
        deadline=time.monotonic()+min(1,self.window.remaining())
        with closing(sqlite3.connect(self.source_domain().as_uri()+'?mode=ro',uri=True,timeout=0.1)) as connection:
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536)
            connection.set_progress_handler(lambda:1 if time.monotonic()>=deadline else 0,100)
            columns=('endpoint','job_id','instance','boot_id','state','demand_mib','refresh_after','dispatched_at','max_leases')
            row=connection.execute('SELECT '+','.join(columns)+' FROM backend_admission WHERE endpoint=? AND job_id=?',
                (settings.ollama_base_url,job['id'])).fetchone()
        require(time.monotonic()<deadline and row is not None,'RESIDENCY_ORIGINAL_LEASE_REQUIRED')
        snapshot=dict(zip(columns,row))
        require(snapshot['state']==('pending' if phase=='PRE_DISPATCH' else 'running'),
            'RESIDENCY_ORIGINAL_LEASE_PHASE_DRIFT')
        try:
            receipt=self.validate_ps(bytes(raw),provider.model,job['id'])
        except ResidencyUnavailable as error:
            receipt=dict(error.receipt,phase=phase,original_lease_snapshot=snapshot)
            if phase=='POST_DISPATCH':raise ResidencyLostAfterDispatch(receipt) from None
            raise ResidencyUnavailable(receipt) from None
        return dict(receipt,phase=phase,original_lease_snapshot=snapshot)
    def completion(self,final,model):
        self.window.remaining()
        require(type(final) is dict and final.get('model')==model and final.get('done') is True,
            'RESIDENCY_NATIVE_COMPLETION_MODEL_DRIFT')
        require(type(final.get('load_duration')) is int and final['load_duration']>=0,
            'RESIDENCY_NATIVE_LOAD_EVIDENCE_REQUIRED')
        # A nonzero native load metric is preserved, never rounded into proof of
        # zero cold loads. Qualification must independently interpret originals.
        return dict(load_duration=final['load_duration'],atomic_no_cold_load_guarantee=False,
            qualification='SOURCE_UNREADY')
    def bind_chat_request(self,payload):
        self.window.remaining();generation=parse(self.generation_binding.encode())
        require(type(generation) is dict,'RESIDENCY_GENERATION_BINDING_REQUIRED')
        if generation:
            require(set(generation)=={'original_public_settings','effective_public_settings','options'}
                and generation['options']=={},'RESIDENCY_GENERATION_OPTIONS_REQUIRED')
            settings=generation['effective_public_settings']
            require(settings['context_tokens']==512 and settings['max_output_tokens']==16
                and payload==dict(model=self.deep_model,messages=[dict(role='user',content=payload['messages'][0]['content'])],
                    stream=True,keep_alive=settings['keep_alive'],options=dict(num_ctx=512,num_predict=16))
                and sha(payload['messages'][0]['content'].encode())==self.prompt_sha256,'RESIDENCY_ACTUAL_PAYLOAD_DRIFT')
        raw=canonical(payload);require(len(raw)<=8192,'RESIDENCY_ACTUAL_PAYLOAD_BOUND')
        require(not self._chat_request_raw,'RESIDENCY_ACTUAL_POST_ALREADY_ATTEMPTED');self._chat_request_raw.extend(raw)

    async def chat_lines(self,response):
        require(response.headers.get('content-encoding','identity')=='identity','RESIDENCY_NATIVE_CHAT_ENCODING_REQUIRED')
        pending=bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            self.window.remaining();require(len(self._chat_raw)+len(chunk)<=MAX_PS,'RESIDENCY_NATIVE_CHAT_BOUND')
            self._chat_raw.extend(chunk);pending.extend(chunk)
            while b'\n' in pending:
                line,rest=pending.split(b'\n',1);pending=bytearray(rest)
                try:yield line.decode('utf-8')
                except UnicodeError:raise ResidencyAdmissionError('RESIDENCY_NATIVE_CHAT_UTF8_REQUIRED') from None
        if pending:
            try:yield pending.decode('utf-8')
            except UnicodeError:raise ResidencyAdmissionError('RESIDENCY_NATIVE_CHAT_UTF8_REQUIRED') from None


def run_source_assessment(queue,*,settings,contract,prompt,ledger):
    """Actual disposable native stores; even simulated HTTP is always UNREADY.

    Trusted source composition only. No service startup, model loading, API mount,
    admission policy change, runtime/credential lookup or certified output.
    """
    import os
    from .job_queue import JobQueue,Provider
    from .action_records import ActionLedger,ActionRecord,DirectExecutor
    from .direct_stream import infer
    from .compute_profile import require_compute_capacity,generation_options
    require(type(contract) is ResidentAdmissionContract and type(queue) is JobQueue
        and type(ledger) is ActionLedger,'RESIDENCY_NATIVE_SOURCE_COMPOSITION_REQUIRED')
    db=contract.source_domain()
    require(queue.db_path==str(db) and queue.backend_endpoint==settings.ollama_base_url
        and queue.policy.global_concurrency==queue.policy.per_agent_concurrency==1
        and type(prompt) is str and 0<len(prompt)<=4096 and sha(prompt.encode())==contract.prompt_sha256,
        'RESIDENCY_NATIVE_SOURCE_COMPOSITION_REQUIRED')
    require(ledger.path.resolve()==contract.domain_root.resolve()/'action-records.jsonl'
        and not ledger.path.is_symlink() and not ledger.path.is_junction(), 'RESIDENCY_OWNED_LEDGER_REQUIRED')
    contract.window.remaining()
    # Exclusive durable claim before the first native mutation. Never replay an
    # uncertain or interrupted source experiment in the same declared domain.
    claim=contract.domain_root/'source-residency-assessment.claim'
    with claim.open('xb') as stream:
        stream.write(canonical(contract.binding));stream.flush();os.fsync(stream.fileno())
    contract.window.remaining();attempts=[]
    def preserve(name,value):
        raw=canonical(value);require(len(raw)<=256*1024,'RESIDENCY_SOURCE_RECEIPT_BOUND')
        with (contract.domain_root/name).open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        return sha(raw)
    for role,model in (('fast',contract.fast_model),('deep',contract.deep_model)):
        contract.window.remaining()
        provider=Provider('ollama-'+role,'local',model,queue.policy.local_ram_mb,queue.policy.local_vram_mb,1)
        submitted=queue.submit(agent='a19',prompt=prompt,priority='low',model_role=role,model=model,
            ram_mb=1024,vram_mb=0,timeout_seconds=5,max_retries=0,max_cost_usd=0,allow_cloud=False,
            external_execution=False,classification='R0',preferred_provider=provider.name,data_classification='LOCAL_ONLY')
        job=queue.claim('source-residency-'+contract.domain_id,[provider])
        require(type(job) is dict and job['id']==submitted['id'],'RESIDENCY_ORIGINAL_NATIVE_CLAIM_REQUIRED')
        job['_admission_db']=str(db);record=ActionRecord(job['id'],'a19','inference.run','ollama',
            parameters_summary=dict(contract_sha256=sha(canonical(contract.binding)),domain_id=contract.domain_id),
            model_backend=model)
        try:
            result=DirectExecutor(ledger).execute(record,lambda:asyncio.run(infer(job,provider,settings=settings,
                capacity=require_compute_capacity,options=generation_options,residency_contract=contract)))
            observation=result.pop('source_residency_admission')
            result['actual_cost_usd']=0
            finished=queue.finish(job['id'],retryable=False,**result)
            require(finished['status']=='completed' and finished['attempts']==1
                and finished['result']==result['result'] and finished['actual_cost_usd']==0,
                'RESIDENCY_ORIGINAL_NATIVE_COMPLETION_REQUIRED')
            require(ledger.flush(timeout=contract.window.remaining()) and ledger.dropped==0,
                'RESIDENCY_ORIGINAL_AUDIT_DURABILITY_REQUIRED')
            contract.window.remaining()
            attempts.append(dict(job=finished,residency=observation,action_id=record.action_id))
            value=dict(state='SOURCE_UNREADY',case=CASE,contract=contract.binding,attempts=attempts,
                fallback_exercised=role=='deep',assessment_result=finished['result'],
                actual_service_health='UNKNOWN',atomic_no_cold_load_guarantee=False,
                reload_consistency='NOT_VERIFIED_NATIVE_METRIC_RETAINED',certification='UNVERIFIED')
            preserve('source-residency-result.json',value);contract.window.remaining();return value
        except Exception as error:
            original=queue.get(job['id'])
            if original['status']=='running':
                original=queue.finish(job['id'],error=str(error) if type(error) is ResidencyUnavailable else type(error).__name__,
                    retryable=False,actual_cost_usd=0)
            evidence=getattr(error,'receipt',None)
            attempts.append(dict(job=original,residency=evidence,action_id=record.action_id))
            preserve('source-residency-'+role+'-failure.json',dict(state='SOURCE_UNREADY',case=CASE,
                contract=contract.binding,attempt=attempts[-1],error_type=type(error).__name__,
                native_chat_utf8=bytes(contract._chat_raw).decode('utf-8',errors='replace')))
            if type(error) is not ResidencyUnavailable or role!='fast':raise
            require(type(evidence) is dict and evidence['job_id']==job['id'] and evidence['model']==model
                and evidence['phase']=='PRE_DISPATCH' and not contract._chat_raw
                and evidence['decision']=='RESIDENCY_UNAVAILABLE' and original['status']=='failed'
                and original['attempts']==1 and original['max_retries']==0,'RESIDENCY_ORIGINAL_DENIAL_REQUIRED')
            require(ledger.flush(timeout=contract.window.remaining()) and ledger.dropped==0,
                'RESIDENCY_ORIGINAL_AUDIT_DURABILITY_REQUIRED')
            contract.window.remaining()
    raise ResidencyAdmissionError('RESIDENCY_NO_COMPLETED_ALTERNATIVE')
