"""Non-authorizing action records and asynchronous, observable audit delivery."""
from dataclasses import dataclass,field,asdict
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
import uuid


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
        self.path=Path(path)
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
                if self.sequence==0 and self.path.exists() and self.path.stat().st_size:
                    last=json.loads(self.path.read_text(encoding='utf-8').splitlines()[-1])
                    self.sequence=last['sequence'];self.previous=last['sha256']
                event={**value,'sequence':self.sequence+1,'previous_sha256':self.previous}
                raw=json.dumps(event,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
                digest=hashlib.sha256(raw).hexdigest()
                with self.path.open('a',encoding='utf-8',newline='\n') as stream:
                    stream.write(json.dumps({**event,'sha256':digest},sort_keys=True)+'\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                self.sequence+=1;self.previous=digest;self.persisted+=1
            except Exception as exc:
                self.dropped+=1
                self.last_error=type(exc).__name__
            finally:self.pending.task_done()

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
