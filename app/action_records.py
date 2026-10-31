"""Non-authorizing actions with asynchronous, cross-process serialized delivery.

The append lock protects only journal bytes, sequence and hash predecessor.
Execution/admission never acquires it. Historical journal bytes are preserved.
"""
from contextlib import contextmanager
from dataclasses import dataclass,field,asdict
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import time
import uuid


APPEND_PROTOCOL = 'orqevia.action-append.v2'


class LedgerTailError(ValueError):
    """The existing tail cannot be safely continued without explicit recovery."""


@contextmanager
def _append_lock(path: Path, timeout=5):
    """Serialize cooperating append workers; never used around mission work."""
    lock_path=path.with_name(path.name+'.append.lock')
    with lock_path.open('a+b') as handle:
        if os.fstat(handle.fileno()).st_size==0:
            handle.write(b'\0');handle.flush()
        deadline=time.monotonic()+timeout
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError as error:
                import errno
                if error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):
                    raise
                if time.monotonic()>=deadline:
                    raise TimeoutError('Action append lock unavailable') from None
                time.sleep(min(.05,max(0,deadline-time.monotonic())))
        try:
            yield
        finally:
            if os.name=='nt':
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def _canonical_event(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def _journal_tail(stream):
    """Read only the last nonempty record, preserving an invalid partial tail."""
    size=os.fstat(stream.fileno()).st_size
    if not size:return None,False
    stream.seek(size-1);needs_newline=stream.read(1)!=b'\n'
    end=size;buffer=b''
    while end:
        start=max(0,end-65536)
        stream.seek(start);buffer=stream.read(end-start)+buffer
        lines=buffer.split(b'\n')
        candidates=lines if start==0 else lines[1:]
        for line in reversed(candidates):
            if not line.strip():continue
            try:
                value=json.loads(line)
                if (type(value) is not dict or type(value.get('sequence')) is not int
                        or not 1<=value['sequence']<2**63
                        or type(value.get('sha256')) is not str
                        or re.fullmatch('[0-9a-f]{64}',value['sha256']) is None
                        or type(value.get('previous_sha256')) is not str
                        or re.fullmatch('[0-9a-f]{64}',value['previous_sha256']) is None
                        or hashlib.sha256(_canonical_event({k:v for k,v in value.items() if k!='sha256'})).hexdigest()!=value['sha256']):
                    raise ValueError()
                return value,needs_newline
            except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
                raise LedgerTailError('Action journal tail is incomplete or invalid; original bytes preserved') from None
        end=start
    return None,needs_newline


def _prefix_boundary(stream, *, needs_newline):
    """Anchor an unqualified prefix once, never rewrite historical collisions."""
    stream.seek(0);digest=hashlib.sha256();counts={};invalid=0;records=0
    reader=io.BufferedReader(stream)
    try:
        for line in reader:
            digest.update(line)
            if not line.strip():continue
            records+=1
            try:
                value=json.loads(line);sequence=value.get('sequence') if type(value) is dict else None
                if type(sequence) is not int or not 1<=sequence<2**63:
                    raise ValueError()
                counts[sequence]=counts.get(sequence,0)+1
            except (ValueError,TypeError,UnicodeError,OverflowError,RecursionError):
                invalid+=1
    finally:
        reader.detach()
    size=os.fstat(stream.fileno()).st_size
    maximum=max(counts,default=0)
    return {'status':'HISTORICAL_PREFIX_UNQUALIFIED' if size else 'EMPTY_PREFIX',
        'prefix_bytes':size,'prefix_sha256':digest.hexdigest(),
        'prefix_records':records,'maximum_sequence':maximum,
        'duplicate_sequence_values':sum(count>1 for count in counts.values()),
        'invalid_sequence_or_json_records':invalid,
        'new_records_start_offset':size+int(bool(size and needs_newline)),
        'scope':'NEW_APPENDS_ONLY_REQUIRES_ALL_WRITERS_USING_APPEND_PROTOCOL',
        'recorded_at':datetime.now(timezone.utc).isoformat()}


def _read_append_state(path):
    try:
        with path.open('rb') as stream:
            raw=stream.read(65537)
        return json.loads(raw) if len(raw)<=65536 else None
    except (OSError,ValueError,TypeError,UnicodeError,RecursionError):
        return None


def _save_append_state(path, state):
    """Atomic auxiliary checkpoint; a stale/missing copy is reconstructed."""
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name)
            stream.write(json.dumps(state,sort_keys=True,separators=(',',':')).encode('utf-8')+b'\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()


@dataclass
class ActionRecord:
    task_id: str
    agent_id: str
    action_type: str
    tool: str
    target: str = ''
    classification: str = 'R0'
    parameters_summary: dict = field(default_factory=dict)
    model_backend: str = 'deterministic'
    execution_location: str = 'local'
    parent_agent: str | None = None
    workflow_id: str | None = None
    action_id: str = field(default_factory=lambda:str(uuid.uuid4()))


def safe(value):
    if isinstance(value,dict):
        return {str(k):'[REDACTED]' if re.search('secret|password|token|credential|api.?key',str(k),re.I) else safe(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [safe(v) for v in value[:100]]
    if isinstance(value,str):return re.sub(r'(?i)Bearer\s+\S+','Bearer [REDACTED]',value)[:4000]
    if value is None or isinstance(value,(int,float,bool)):return value
    return type(value).__name__


class ActionLedger:
    def __init__(self,path: Path,capacity=1024):
        self.path=Path(path).resolve()
        self.pending=queue.Queue(maxsize=capacity)
        self.persisted=0
        self.dropped=0
        self.last_error=None
        self.sequence=0
        self.previous='0'*64
        self.closed=False
        self.emit_lock=threading.Lock()
        self.worker=threading.Thread(target=self._write,name='action-observability',daemon=True)
        self.worker.start()

    def emit(self,record: ActionRecord,phase: str,**details):
        try:
            event=safe({**asdict(record),'phase':phase,'timestamp':datetime.now(timezone.utc).isoformat(),**details})
            with self.emit_lock:
                if self.closed:raise RuntimeError('Ledger closed')
                self.pending.put_nowait(('event',event))
            return 'BUFFERED'
        except Exception as exc:
            self.dropped+=1
            self.last_error=type(exc).__name__
            return 'NOT_RECORDED'

    def _write(self):
        while True:
            kind,value=self.pending.get()
            try:
                if kind=='stop':return
                if kind=='flush':value.set();continue
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with _append_lock(self.path):
                    self._append(value)
            except Exception as exc:
                self.dropped+=1
                self.last_error=type(exc).__name__
            finally:self.pending.task_done()

    def _append(self, value):
        state_path=self.path.with_name(self.path.name+'.append-state.json')
        # Opening/re-reading happens inside the common append lock. Cached
        # writer counters are observations only, never sequence authority.
        with self.path.open('a+b',buffering=0) as stream:
            last,needs_newline=_journal_tail(stream)
            before=os.fstat(stream.fileno())
            state=_read_append_state(state_path)
            identity=[before.st_dev,before.st_ino]
            matches=(type(state) is dict and state.get('protocol')==APPEND_PROTOCOL
                and state.get('journal_identity')==identity and state.get('journal_bytes')==before.st_size
                and last is not None and state.get('sequence')==last['sequence']
                and state.get('sha256')==last['sha256'] and type(state.get('qualification_boundary')) is dict)
            boundary=state['qualification_boundary'] if matches else _prefix_boundary(stream,needs_newline=needs_newline)
            sequence=(last['sequence'] if matches else max(boundary['maximum_sequence'],last['sequence'] if last else 0))+1
            if sequence>=2**63:raise LedgerTailError('Action journal sequence exceeds supported format')
            previous=last['sha256'] if last else '0'*64
            event={k:v for k,v in value.items() if k not in {'sequence','previous_sha256','sha256'}}
            event.update(sequence=sequence,previous_sha256=previous)
            # Do not add protocol/boundary fields to action records: existing
            # exact-field attestation readers keep their original contracts.
            digest=hashlib.sha256(_canonical_event(event)).hexdigest()
            raw=(b'\n' if before.st_size and needs_newline else b'')+(
                json.dumps({**event,'sha256':digest},sort_keys=True)+'\n').encode('utf-8')
            remaining=memoryview(raw)
            while remaining:
                written=stream.write(remaining)
                if not written:raise OSError('Action append did not progress')
                remaining=remaining[written:]
            os.fsync(stream.fileno())
            after=os.fstat(stream.fileno())
            _save_append_state(state_path,{'protocol':APPEND_PROTOCOL,
                'journal_identity':[after.st_dev,after.st_ino],'journal_bytes':after.st_size,
                'sequence':sequence,'sha256':digest,'qualification_boundary':boundary})
            self.sequence=sequence;self.previous=digest;self.persisted+=1

    def status(self):
        return {'persisted':self.persisted,'pending':self.pending.qsize(),'dropped':self.dropped,
                'last_error':self.last_error,'healthy':self.last_error is None and self.dropped==0}

    def flush(self,timeout=5):
        marker=threading.Event()
        try:self.pending.put(('flush',marker),timeout=timeout)
        except queue.Full:return False
        return marker.wait(timeout) and self.status()['healthy']

    def close(self):
        with self.emit_lock:
            if self.closed:return not self.worker.is_alive() and self.status()['healthy']
            self.closed=True
        flushed=self.flush()
        try:self.pending.put(('stop',None),timeout=1)
        except queue.Full:return False
        self.worker.join(timeout=2)
        return flushed and not self.worker.is_alive()


class DirectExecutor:
    def __init__(self,ledger: ActionLedger):self.ledger=ledger

    def _emit(self,record,phase,**details):
        try:return self.ledger.emit(record,phase,**details)
        except Exception as exc:
            self.ledger=UnavailableLedger(type(exc).__name__)
            return self.ledger.emit(record,phase,**details)

    def execute(self,record: ActionRecord,operation):
        start=time.perf_counter()
        self._emit(record,'started')
        try:result=operation()
        except Exception as exc:
            self._emit(record,'completed',success=False,error=type(exc).__name__,duration_ms=(time.perf_counter()-start)*1000)
            raise
        summary={'type':type(result).__name__}
        if isinstance(result,dict):
            summary.update({key:safe(result[key]) for key in ('id','artifact_id','sha256','location','status','fuel_consumed','source_sha256') if key in result})
            output=result.get('result')
            if isinstance(output,str):summary.update(output_sha256=hashlib.sha256(output.encode()).hexdigest(),output_length=len(output))
            elif isinstance(output,(int,float,bool)):summary['value']=output
        elif isinstance(result,(int,float,bool)):summary['value']=result
        self._emit(record,'completed',success=True,duration_ms=(time.perf_counter()-start)*1000,result_summary=summary)
        return result


class UnavailableLedger:
    def __init__(self,error):self.error=error;self.dropped=0
    def emit(self,*args,**kwargs):self.dropped+=1;return 'NOT_RECORDED'
    def status(self):return {'persisted':0,'pending':0,'dropped':self.dropped,'last_error':self.error,'healthy':False}
    def flush(self,*args,**kwargs):return False
    def close(self):return False


_ledgers={}
_lock=threading.Lock()
def action_ledger():
    with _lock:
        key=os.getenv('PRIME_DATA_DIR','/data')
        if key not in _ledgers:
            try:_ledgers[key]=ActionLedger(Path(key)/'action-records.jsonl')
            except Exception as exc:_ledgers[key]=UnavailableLedger(type(exc).__name__)
        return _ledgers[key]


def close_ledgers():
    with _lock:
        results=[ledger.close() for ledger in _ledgers.values()]
        _ledgers.clear()
    return all(results)
