"""Real process contention/restart/partial-tail checks in disposable journals."""
from dataclasses import asdict
import hashlib
import json
import multiprocessing
from pathlib import Path

from app.action_records import ActionLedger,ActionRecord,DirectExecutor,_append_lock


def _assert_chain(rows, *, first_sequence=1, previous='0'*64):
    for sequence,row in enumerate(rows,start=first_sequence):
        assert row['sequence']==sequence
        assert row['previous_sha256']==previous
        payload={key:value for key,value in row.items() if key!='sha256'}
        assert row['sha256']==hashlib.sha256(json.dumps(payload,sort_keys=True,
            separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        previous=row['sha256']


def _append_in_process(filename, worker, barrier, results):
    """Top-level spawn target works on Windows and Linux without a model."""
    ledger=ActionLedger(Path(filename),capacity=100)
    try:
        executor=DirectExecutor(ledger)
        barrier.wait(timeout=20)
        executor.execute(ActionRecord(f'fixture-{worker}-prime','a17','test','fixture'),lambda:worker)
        assert ledger.flush(timeout=20)
        # All old per-writer counters have now been primed. Every subsequent
        # append must still derive order from the shared tail under its lock.
        barrier.wait(timeout=20)
        for index in range(10):
            executor.execute(ActionRecord(f'fixture-{worker}-{index}','a17','test','fixture'),lambda:index)
        assert ledger.flush(timeout=20)
        assert ledger.close()
        results.put({'worker':worker,'healthy':True})
    except BaseException as error:
        ledger.close()
        results.put({'worker':worker,'healthy':False,'error_class':type(error).__name__})
        raise


def _legacy_row(sequence, previous='0'*64):
    value={'sequence':sequence,'previous_sha256':previous,'phase':'fixture'}
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return {**value,'sha256':hashlib.sha256(raw).hexdigest()}


def _encoded(row, newline=True):
    return json.dumps(row,sort_keys=True).encode()+(b'\n' if newline else b'')


def test_multiprocess_writers_share_one_sequence_and_hash_chain(tmp_path):
    path=tmp_path/'audit.jsonl'
    context=multiprocessing.get_context('spawn')
    barrier=context.Barrier(3);results=context.Queue()
    processes=[context.Process(target=_append_in_process,args=(str(path),worker,barrier,results))
        for worker in range(3)]
    try:
        for process in processes:process.start()
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode==0
        assert all(results.get(timeout=5)['healthy'] for _ in processes)
    finally:
        for process in processes:
            if process.is_alive():process.terminate();process.join(timeout=5)
        results.close();results.join_thread()
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(rows)==66 and len({r['sequence'] for r in rows})==66
    _assert_chain(rows)


def test_independent_live_writers_and_restart_reread_the_actual_tail(tmp_path):
    path=tmp_path/'audit.jsonl'
    first=ActionLedger(path);second=ActionLedger(path)
    try:
        assert first.emit(ActionRecord('first','a17','test','fixture'),'started')=='BUFFERED'
        assert first.flush()
        assert second.emit(ActionRecord('second','a17','test','fixture'),'started')=='BUFFERED'
        assert second.flush()
        first.emit(ActionRecord('third','a17','test','fixture'),'started');assert first.flush()
    finally:
        first.close();second.close()
    prefix=path.read_bytes()
    restarted=ActionLedger(path)
    restarted.emit(ActionRecord('after-restart','a17','test','fixture'),'started')
    assert restarted.close()
    assert path.read_bytes().startswith(prefix)
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    _assert_chain(rows)


def test_legacy_duplicates_are_preserved_and_new_sequence_exceeds_prefix_maximum(tmp_path):
    path=tmp_path/'audit.jsonl'
    legacy=[_legacy_row(5),_legacy_row(8),_legacy_row(5)]
    prefix=b''.join(_encoded(row) for row in legacy);path.write_bytes(prefix)
    ledger=ActionLedger(path)
    ledger.emit(ActionRecord('new','a17','test','fixture'),'started')
    assert ledger.close()
    assert path.read_bytes().startswith(prefix)
    rows=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    _assert_chain(rows[3:],first_sequence=9,previous=legacy[-1]['sha256'])
    state=json.loads(path.with_name(path.name+'.append-state.json').read_text())
    boundary=state['qualification_boundary']
    assert boundary['status']=='HISTORICAL_PREFIX_UNQUALIFIED'
    assert boundary['maximum_sequence']==8 and boundary['duplicate_sequence_values']==1
    assert boundary['prefix_sha256']==hashlib.sha256(prefix).hexdigest()
    assert boundary['prefix_bytes']==len(prefix)


def test_stale_checkpoint_after_a_durable_append_is_reconstructed_without_replay(tmp_path):
    path=tmp_path/'audit.jsonl'
    ledger=ActionLedger(path);ledger.emit(ActionRecord('first','a17','test','fixture'),'started')
    assert ledger.close()
    first=json.loads(path.read_text().splitlines()[-1])
    # Simulate process death after a durable journal append but before its
    # auxiliary checkpoint update. The original append remains authoritative.
    appended=_legacy_row(first['sequence']+1,first['sha256'])
    with path.open('ab') as stream:stream.write(_encoded(appended))
    prefix=path.read_bytes()
    restarted=ActionLedger(path);restarted.emit(ActionRecord('third','a17','test','fixture'),'started')
    assert restarted.close()
    assert path.read_bytes().startswith(prefix)
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    _assert_chain(rows)


def test_valid_complete_tail_without_newline_is_delimited_without_rewriting_bytes(tmp_path):
    path=tmp_path/'audit.jsonl'
    legacy=_legacy_row(1);prefix=_encoded(legacy,newline=False);path.write_bytes(prefix)
    ledger=ActionLedger(path);ledger.emit(ActionRecord('second','a17','test','fixture'),'started')
    assert ledger.close()
    assert path.read_bytes().startswith(prefix+b'\n')
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    _assert_chain(rows)


def test_invalid_partial_tail_preserves_bytes_and_does_not_block_work_execution(tmp_path):
    path=tmp_path/'audit.jsonl'
    prefix=_encoded(_legacy_row(1))+b'{"sequence":2,"phase":"star'
    path.write_bytes(prefix)
    ledger=ActionLedger(path)
    assert DirectExecutor(ledger).execute(ActionRecord('live-work','a17','test','fixture'),lambda:42)==42
    assert not ledger.flush()
    assert ledger.status()['last_error']=='LedgerTailError'
    assert path.read_bytes()==prefix
    ledger.close()


def test_append_lock_only_delays_logging_and_keeps_existing_event_schema(tmp_path):
    path=tmp_path/'audit.jsonl'
    ledger=ActionLedger(path)
    record=ActionRecord('fixture','a17','test','fixture')
    try:
        with _append_lock(path):
            assert DirectExecutor(ledger).execute(record,lambda:'work completed')=='work completed'
        assert ledger.flush()
    finally:
        ledger.close()
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    common=set(asdict(record))|{'phase','timestamp','sequence','previous_sha256','sha256'}
    assert set(rows[0])==common
    assert set(rows[1])==common|{'success','duration_ms','result_summary'}
    _assert_chain(rows)


def test_emitter_details_cannot_choose_reserved_sequence_or_digest_fields(tmp_path):
    path=tmp_path/'audit.jsonl'
    ledger=ActionLedger(path)
    ledger.emit(ActionRecord('fixture','a17','test','fixture'),'started',
        sequence=999,previous_sha256='f'*64,sha256='e'*64)
    assert ledger.close()
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    _assert_chain(rows)
