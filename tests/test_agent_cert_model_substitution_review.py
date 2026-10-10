"""Pure/disposable custody negatives; simulated transport never qualifies a case."""
import json,os,sqlite3,subprocess,time
from pathlib import Path
import pytest
from app import agent_cert_model_substitution_review as review
from tests.test_agent_cert_model_substitution_chain import source_runtime,subject,configured,runtime

def deadline():return time.monotonic()+2

@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":NaN}',b'{"x":Infinity}',b'not-json',b''])
def test_original_json_rejects_duplicate_nonfinite_or_missing(raw):
    with pytest.raises(review.SubstitutionReviewError):review.parse(raw)

def test_actual_bounded_read_rejects_growth_before_original_read(tmp_path,monkeypatch):
    path=tmp_path/'original.json';path.write_bytes(b'{}');original=Path.open;reads=[]
    class Grow:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,count):
            reads.append(count)
            with original(path,'ab') as writer:writer.write(b' '*(65536+1))
            return self.stream.read(count)
    def opened(self,*args,**kwargs):
        stream=original(self,*args,**kwargs)
        return Grow(stream) if self==path and args and args[0]=='rb' else stream
    monkeypatch.setattr(Path,'open',opened)
    with pytest.raises(review.SubstitutionReviewError,match='ORIGINAL_FILE_CHANGED'):
        review.original_bytes(path,65536,deadline())
    assert reads==[65537]

def test_actual_file_swap_after_original_close_rejects(tmp_path,monkeypatch):
    path=tmp_path/'original.json';path.write_bytes(b'{}');replacement=tmp_path/'replacement.json';replacement.write_bytes(b'{ }')
    original=Path.open
    class Swap:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):
            result=self.stream.__exit__(*args);path.replace(tmp_path/'retained.json');replacement.replace(path);return result
        def fileno(self):return self.stream.fileno()
        def read(self,count):return self.stream.read(count)
    def opened(self,*args,**kwargs):
        stream=original(self,*args,**kwargs)
        return Swap(stream) if self==path and args and args[0]=='rb' else stream
    monkeypatch.setattr(Path,'open',opened)
    with pytest.raises(review.SubstitutionReviewError,match='ORIGINAL_FILE_CHANGED'):
        review.original_bytes(path,65536,deadline())

@pytest.mark.parametrize('name',['objectives.db','compute-queue.db'])
@pytest.mark.parametrize('defect',['oversized_shm','aggregate_shm','junction_shm'])
def test_native_original_shm_boundary_fails_before_sqlite(tmp_path,monkeypatch,name,defect):
    db=tmp_path/name;db.write_bytes(b'x')
    shm=Path(str(db)+'-shm')
    if defect=='oversized_shm':shm.write_bytes(b'x'*(8*1024*1024+1))
    elif defect=='aggregate_shm':
        db.write_bytes(b'x'*(4*1024*1024));shm.write_bytes(b'x'*(4*1024*1024+1))
    else:
        if os.name!='nt':pytest.skip('Actual native Windows reparse negative')
        target=tmp_path/'target';target.mkdir()
        result=subprocess.run(['cmd','/c','mklink','/J',str(shm),str(target)],capture_output=True)
        assert result.returncode==0
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k:pytest.fail('Unsafe original database opened'))
    try:
        with pytest.raises(review.SubstitutionReviewError):review.database(tmp_path,name,deadline())
    finally:
        if defect=='junction_shm':os.rmdir(shm)

def test_original_shared_deadline_exhaustion_reads_nothing(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'open',lambda *a,**k:pytest.fail('Expired original read attempted'))
    with pytest.raises(review.SubstitutionReviewError,match='SHARED_DEADLINE'):
        review.original_bytes(tmp_path/'absent',65536,time.monotonic()-1)

def test_owning_native_input_contract_does_not_accept_other_execution_schema(tmp_path):
    with pytest.raises(review.SubstitutionReviewError,match='EXECUTION_ENVELOPE'):
        review.validate_original_execution({},root=tmp_path,runtime={},registry_sha256='0'*64,deadline=deadline())

@pytest.mark.parametrize('field',['instance','boot_id'])
def test_original_golden_n1_snapshot_cannot_invent_backend_identity(source_runtime,field):
    execution=subject(source_runtime)
    native=execution['native_result'];attempt=native['attempts'][0]
    assert attempt['residency']['original_lease_snapshot'][field]==''
    attempt['residency']['original_lease_snapshot'][field]='invented-backend-identity'
    with pytest.raises(review.SubstitutionReviewError,match='ORIGINAL_LEASE_SNAPSHOT'):
        review.native_ps(attempt['residency'],attempt['job'],native['contract'],
            'PRE_DISPATCH','RESIDENCY_UNAVAILABLE',deadline())

def grade(source_runtime,execution):
    return review.validate_original_execution(execution,root=source_runtime.root,runtime=execution['runtime'],
        registry_sha256=execution['registry_sha256'],deadline=time.monotonic()+5)

def test_exact_original_receipt_byte_change_between_reads_rejected(source_runtime,monkeypatch):
    execution=subject(source_runtime);original=review.original_native;calls=[]
    def changing(*args,**kwargs):
        result=original(*args,**kwargs);calls.append(True)
        if len(calls)==1:
            path=source_runtime.root/'source-residency-result.json'
            path.write_bytes(path.read_bytes()+b' ')
        return result
    monkeypatch.setattr(review,'original_native',changing)
    with pytest.raises(review.SubstitutionReviewError,match='CHANGED_BETWEEN_READS'):
        grade(source_runtime,execution)
    assert len(calls)==2

@pytest.mark.parametrize('stage',['setup','input_read','result','native_output'])
def test_original_ledger_summary_must_bind_actual_artifact_or_native_output(source_runtime,stage):
    execution=subject(source_runtime);path=source_runtime.root/'action-records.jsonl'
    identifier=(execution['native_result']['attempts'][1]['action_id'] if stage=='native_output'
        else execution['case_action_ids'][stage])
    rows=[json.loads(line) for line in path.read_bytes().splitlines()];previous='0'*64
    for row in rows:
        if row['action_id']==identifier and row['phase']=='completed':
            row['result_summary']['sha256' if stage in ('setup','result') else 'output_sha256']='0'*64
        row.pop('sha256');row['previous_sha256']=previous
        row['sha256']=review.sha(review.canonical(row));previous=row['sha256']
    path.write_bytes(b''.join(review.canonical(row)+b'\n' for row in rows))
    with pytest.raises(review.SubstitutionReviewError,match='ACTION_OUTPUT'):
        grade(source_runtime,execution)
