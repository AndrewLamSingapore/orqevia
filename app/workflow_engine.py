"""Dependency-aware direct scheduling within bounded worker capacity."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import time

from .agent_registry import canonical_agent_id


@dataclass(frozen=True)
class Task:
    id: str
    dependencies: tuple[str,...]
    agent: str
    operation: str
    priority: int = 50
    tier: str = 'NANO'
    compute: str = 'deterministic'
    authority_class: str = 'R0'


def validate(tasks: tuple[Task,...]):
    ids={task.id for task in tasks}
    if len(ids)!=len(tasks) or not ids or len(ids)>100:raise ValueError('Invalid task identities or count')
    for task in tasks:
        canonical_agent_id(task.agent)
        if not set(task.dependencies)<=ids or task.id in task.dependencies:raise ValueError('Invalid dependency')
        if task.authority_class not in {'R0','R1','R2','R3','consequential'}:raise ValueError('Unknown authority class')
    resolved=set()
    while len(resolved)<len(ids):
        ready={task.id for task in tasks if set(task.dependencies)<=resolved}-resolved
        if not ready:raise ValueError('Dependency cycle')
        resolved.update(ready)


def execute(tasks: tuple[Task,...], handlers: dict, inputs: dict, *, workers: int=3) -> dict:
    validate(tasks)
    # Explicit structured handoffs are validated before any handler executes.
    # Ordinary workflows without the optional key retain existing behavior.
    handoff_snapshot = None
    if 'handoff' in inputs:
        from .handoff import validate_handoff
        handoff_snapshot = validate_handoff(inputs['handoff'])
    started=time.perf_counter()
    pending={task.id:task for task in tasks}
    complete={}
    running={}
    def run(task):
        tick=time.perf_counter()
        try:
            if task.operation not in handlers:raise LookupError('Operation unavailable')
            # Classification is metadata; registered handlers execute directly.
            from .action_records import ActionRecord,DirectExecutor,action_ledger
            record=ActionRecord(task.id,task.agent,task.operation,'workflow',classification=task.authority_class)
            task_inputs = inputs if handoff_snapshot is None else {
                **inputs, 'handoff': json.loads(json.dumps(handoff_snapshot))}
            result=DirectExecutor(action_ledger()).execute(record,lambda:handlers[task.operation](task,task_inputs,{key:complete[key] for key in task.dependencies}))
            return {'status':'COMPLETED','result':result,'seconds':time.perf_counter()-tick}
        except Exception as exc:
            return {'status':'FAILED','error':type(exc).__name__,'seconds':time.perf_counter()-tick}
    with ThreadPoolExecutor(max_workers=max(1,min(8,workers))) as pool:
        while pending or running:
            for task in sorted(tuple(pending.values()),key=lambda item:(-item.priority,item.id)):
                if not set(task.dependencies)<=complete.keys():continue
                if any(complete[key]['status']!='COMPLETED' for key in task.dependencies):
                    complete[task.id]={'status':'BLOCKED','reason':'Dependency failed'}
                    pending.pop(task.id)
                elif len(running)<max(1,min(8,workers)):
                    running[pool.submit(run,task)]=task.id
                    pending.pop(task.id)
            if running:
                done,_=wait(running,return_when=FIRST_COMPLETED)
                for future in done:complete[running.pop(future)]=future.result()
    return {'tasks':complete,'seconds':time.perf_counter()-started,
            'status':'COMPLETED' if all(x['status']=='COMPLETED' for x in complete.values()) else 'COMPLETED_WITH_FAILURES'}


def save_template(path: Path, *, name: str, version: str, tasks: tuple[Task,...], input_names: list[str]) -> str:
    validate(tasks)
    value={'name':name,'version':version,'tasks':[asdict(task) for task in tasks],
           'inputs':input_names,'authority':'Template reuse does not grant execution authority'}
    raw=json.dumps(value,sort_keys=True,indent=2).encode()
    with Path(path).open('xb') as stream:stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def load_template(path: Path, expected_sha256: str) -> tuple[Task,...]:
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('Workflow integrity mismatch')
    value=json.loads(raw)
    tasks=tuple(Task(**{**item,'dependencies':tuple(item['dependencies'])}) for item in value['tasks'])
    validate(tasks)
    return tasks
