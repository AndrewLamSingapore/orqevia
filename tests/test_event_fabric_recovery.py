import json
import multiprocessing
import sqlite3
import threading
import hashlib
import sys
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.event_fabric import EventFabric
from app.memory import MemoryStore


def event(identity='event-race-0001', source='the-portal', subject='local-subject-1'):
    return {'schema_version':'1.0.0','event_id':identity,
            'event_type':'velyqua.observation.recorded','source':source,
            'occurred_at':'2026-10-13T00:00:00Z','correlation_id':'recovery-fixture',
            'evidence_level':'E1','provenance':['fixture:offline-only'],
            'subject_id':subject,'payload':{'label':'original','url':'https://example.test/original'}}


def episode_fields(value):
    return {'event_type':'portfolio.'+value['event_type'],
            'content':{'event_id':value['event_id'],'payload':value['payload'],
                       'provenance':value['provenance'],'evidence_level':value['evidence_level']},
            'source':'portfolio:'+value['source'],'salience':.25}


class BarrierMemory:
    def __init__(self, real, barrier):
        self.real, self.barrier = real, barrier

    def record_episode(self, **kwargs):
        self.barrier.wait(timeout=15)
        return self.real.record_episode(**kwargs)


def test_same_event_race_uses_one_real_memory_commit(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    fabric = EventFabric(str(tmp_path/'events.db'), BarrierMemory(memory, threading.Barrier(2)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: fabric.ingest(event()), range(2)))
    assert all(result['projected'] for result in results)
    episodes = memory.recent_episodes()
    assert len(episodes) == 1 and len(fabric.recent()) == 1
    assert {r['projections'][0]['details']['episode_id'] for r in results} == {episodes[0]['episode_id']}


def test_separate_instances_share_durable_binding(tmp_path):
    barrier = threading.Barrier(2)
    memories = [MemoryStore(str(tmp_path/'memory.db')) for _ in range(2)]
    fabrics = [EventFabric(str(tmp_path/'events.db'), BarrierMemory(m, barrier)) for m in memories]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda f: f.ingest(event()), fabrics))
    assert all(r['projected'] for r in results)
    assert len(memories[0].recent_episodes()) == 1


def process_ingest(path, barrier, output):
    try:
        memory = MemoryStore(str(path/'memory.db'))
        class ProcessMemory:
            def record_episode(self, **kwargs):
                barrier.wait(timeout=15)
                return memory.record_episode(**kwargs)
        fabric = EventFabric(str(path/'events.db'), ProcessMemory())
        output.put({'result':fabric.ingest(event())})
    except BaseException as exc:
        output.put({'error':type(exc).__name__})


def test_separate_processes_share_durable_binding(tmp_path):
    # Real independent SQLite connections/processes, not an in-process lock.
    context = multiprocessing.get_context('spawn')
    barrier, output = context.Barrier(2), context.Queue()
    workers = [context.Process(target=process_ingest, args=(tmp_path, barrier, output)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        results = [output.get(timeout=25) for _ in workers]
        assert all(r.get('result', {}).get('projected') for r in results), results
    finally:
        for worker in workers:
            worker.join(timeout=5)
            if worker.is_alive():
                worker.terminate(); worker.join(timeout=5)
        output.close()
    assert all(worker.exitcode == 0 for worker in workers)
    assert len(MemoryStore(str(tmp_path/'memory.db')).recent_episodes()) == 1


@pytest.mark.parametrize('crash', [RuntimeError, KeyboardInterrupt])
def test_commit_before_projector_receipt_survives_reopen(tmp_path, crash):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    committed = []
    class CrashMemory:
        def record_episode(self, **kwargs):
            result = memory.record_episode(**kwargs)
            committed.append(result['episode_id'])
            raise crash('fixture fault after committed episode before projector receipt')
    fabric = EventFabric(str(tmp_path/'events.db'), CrashMemory())
    if crash is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            fabric.ingest(event())
        with fabric.connect() as db:
            assert db.execute("select count(*) from event_projections where projector='governed_memory_candidate'").fetchone()[0] == 0
    else:
        first = fabric.ingest(event())
        assert not first['projected']
        assert first['projections'][0]['details']['error'] == 'RuntimeError'
    reopened = EventFabric(str(tmp_path/'events.db'), MemoryStore(str(tmp_path/'memory.db')))
    result = reopened.ingest(event())
    assert result['projected'] and not result['inserted']
    assert result['projections'][0]['details']['episode_id'] == committed[0]
    assert result['projections'][0]['details']['memory_idempotency']['state'] == 'REPLAYED'
    assert len(reopened.memory.recent_episodes()) == 1


def test_inbox_conflict_remains_rejected_without_new_episode(tmp_path):
    fabric = EventFabric(str(tmp_path/'events.db'))
    fabric.ingest(event())
    with pytest.raises(ValueError, match='different canonical event'):
        fabric.ingest({**event(), 'payload':{'label':'conflicting'}})
    assert len(fabric.memory.recent_episodes()) == 1
    assert fabric.recent()[0]['payload'] == event()['payload']


def test_entire_canonical_event_fingerprint_catches_non_memory_field_conflict(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    first = EventFabric(str(tmp_path/'first.db'), memory)
    second = EventFabric(str(tmp_path/'second.db'), memory)
    assert first.ingest(event())['projected']
    changed = {**event(), 'correlation_id':'different-canonical-event'}
    result = second.ingest(changed)
    assert not result['projected']
    assert result['projections'][0]['details']['error'] == 'ValueError'
    assert len(memory.recent_episodes()) == 1


def test_historical_guid_and_identical_duplicate_history_are_adopted(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    originals = [memory.record_episode(**episode_fields(event())) for _ in range(2)]
    before = memory.recent_episodes()
    fabric = EventFabric(str(tmp_path/'events.db'), memory)
    result = fabric.ingest(event())
    details = result['projections'][0]['details']
    assert result['projected']
    assert details['episode_id'] == originals[0]['episode_id']
    assert details['memory_idempotency']['origin'] == 'ADOPTED_LEGACY'
    assert details['memory_idempotency']['retained_duplicate_episode_ids'] == [originals[1]['episode_id']]
    assert not details['memory_idempotency']['historical_full_event_fingerprint_available']
    assert memory.recent_episodes() == before
    reopened = EventFabric(str(tmp_path/'events.db'), MemoryStore(str(tmp_path/'memory.db')))
    assert reopened.ingest(event())['projections'][0]['details']['episode_id'] == originals[0]['episode_id']
    assert reopened.memory.recent_episodes() == before


def test_conflicting_legacy_episode_is_explicit_without_compensating_insert(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    memory.record_episode(**episode_fields(event()))
    memory.record_episode(**episode_fields({**event(), 'payload':{'label':'conflicting'}}))
    before = memory.recent_episodes()
    result = EventFabric(str(tmp_path/'events.db'), memory).ingest(event())
    assert not result['projected']
    assert 'reconciliation required' in result['projections'][0]['details']['message']
    assert memory.recent_episodes() == before
    with memory.connect() as db:
        assert db.execute('select count(*) from episode_idempotency').fetchone()[0] == 0


def test_memory_episode_and_key_rollback_together(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    with memory.connect() as db:
        db.execute("create trigger reject_key before insert on episode_idempotency begin select raise(ABORT,'fixture key fault'); end")
    with pytest.raises(sqlite3.IntegrityError, match='fixture key fault'):
        memory.record_episode(**episode_fields(event()), idempotency_key=event()['event_id'])
    assert memory.recent_episodes() == []
    with memory.connect() as db:
        assert db.execute('select count(*) from episode_idempotency').fetchone()[0] == 0


def test_two_original_sources_keep_distinct_graph_identities_and_local_ids(tmp_path):
    fabric = EventFabric(str(tmp_path/'events.db'))
    for identity, source in [('event-portal-0001','the-portal'),('event-velyqua-0001','velyqua')]:
        assert fabric.ingest(event(identity, source))['projected']
    graph = fabric.graph()
    assert len(graph) == 2
    assert {node['node_id'] for node in graph} == {'local-subject-1'}
    assert {json.loads(node['scoped_node_id'])[0] for node in graph} == {'the-portal','velyqua'}
    assert len({node['scoped_node_id'] for node in graph}) == 2
    for node in graph:
        assert node['attributes']['source'] == node['source']
        assert node['attributes']['payload']['url'] == 'https://example.test/original'
    assert fabric.graph(source='the-portal')[0]['last_event_id'] == 'event-portal-0001'
    assert len(fabric.recent()) == 2


def legacy_database(path, *, schema_version=True, orphan=False, malformed=False):
    with sqlite3.connect(path) as db:
        db.executescript('''create table portfolio_events(event_id text primary key,SCHEMA event_type text not null,source text not null,occurred_at text not null,evidence_level text not null,correlation_id text not null,subject_id text,provenance_json text not null,payload_json text not null,received_at text not null);
            create table semantic_graph_nodes(node_id text primary key,node_type text not null,label text not null,attributes_json text not null,last_event_id text not null,updated_at text not null);'''.replace('SCHEMA','schema_version text not null,' if schema_version else ''))
        for index, source in enumerate(['the-portal','velyqua']):
            value = event('legacy-event-'+str(index), source)
            values = (value['event_id'],)+(('1.0.0',) if schema_version else ())+(value['event_type'],value['source'],value['occurred_at'],value['evidence_level'],value['correlation_id'],value['subject_id'],json.dumps(value['provenance']),json.dumps(value['payload']),f'2026-10-13T00:00:0{index}Z')
            db.execute('insert into portfolio_events values('+','.join('?' for _ in values)+')', values)
        db.execute('insert into semantic_graph_nodes values(?,?,?,?,?,?)',('local-subject-1','velyqua','historical-final-label',json.dumps({'source':'velyqua','legacy':True}),'legacy-event-1','2026-10-13T00:00:01Z'))
        if orphan:
            db.execute('insert into semantic_graph_nodes values(?,?,?,?,?,?)',('orphan-local-id','unknown','retained orphan',json.dumps({'source':'untrusted-hint'}),'missing-inbox-event','2026-10-13T00:00:02Z'))
        if malformed:
            db.execute("update portfolio_events set payload_json='[]' where event_id='legacy-event-1'")
        return db.execute('select * from semantic_graph_nodes order by node_id').fetchall()


@pytest.mark.parametrize('schema_version', [True, False])
def test_additive_migration_recovers_inbox_sources_without_touching_old_graph_or_memory(tmp_path, schema_version):
    path = tmp_path/'events.db'
    original = legacy_database(path, schema_version=schema_version)
    fabric = EventFabric(str(path))
    assert len(fabric.graph()) == 2
    assert fabric.memory.recent_episodes() == []
    assert {row['last_event_id'] for row in fabric.graph()} == {'legacy-event-0','legacy-event-1'}
    with fabric.connect() as db:
        assert [tuple(row) for row in db.execute('select * from semantic_graph_nodes order by node_id')] == original
        assert db.execute('select count(*) from event_projections').fetchone()[0] == 0
    assert fabric.legacy_graph()[0]['label'] == 'historical-final-label'
    assert not fabric.graph_recovery_status()['original_http_bytes_recovered']
    reopened = EventFabric(str(path))
    assert reopened.graph() == fabric.graph()


def test_orphan_legacy_node_stays_unresolved_instead_of_using_source_hint(tmp_path):
    original = legacy_database(tmp_path/'events.db', orphan=True)
    fabric = EventFabric(str(tmp_path/'events.db'))
    orphan = next(node for node in fabric.graph() if node['node_id']=='orphan-local-id')
    assert orphan['source'] is None and orphan['scoped_node_id'] is None
    assert orphan['namespace_status'] == 'LEGACY_SOURCE_UNRESOLVED'
    assert fabric.graph_recovery_status()['unresolved_legacy_node_ids'] == ['orphan-local-id']
    assert len(fabric.graph(source='the-portal')) == 1
    with fabric.connect() as db:
        assert [tuple(row) for row in db.execute('select * from semantic_graph_nodes order by node_id')] == original


def test_unreconstructible_inbox_record_remains_explicit(tmp_path):
    legacy_database(tmp_path/'events.db', malformed=True)
    fabric = EventFabric(str(tmp_path/'events.db'))
    status = fabric.graph_recovery_status()
    assert status['unreconstructible_event_ids'] == ['legacy-event-1']
    assert status['unresolved_legacy_node_ids'] == ['local-subject-1']
    assert any(node['namespace_status']=='LEGACY_SOURCE_UNRESOLVED' for node in fabric.graph())


def test_old_projector_retry_does_not_replace_newer_same_source_node(tmp_path):
    fabric = EventFabric(str(tmp_path/'events.db'))
    old = event('event-older-0001')
    new = {**event('event-newer-0001'), 'payload':{'label':'newer'}}
    fabric.ingest(old); fabric.ingest(new)
    with fabric.connect() as db:
        db.execute("delete from event_projections where event_id=? and projector='semantic_graph'", (old['event_id'],))
    assert fabric.ingest(old)['projected']
    assert fabric.graph()[0]['last_event_id'] == new['event_id']
    assert fabric.graph()[0]['attributes']['payload'] == new['payload']


def test_legacy_recovery_lookup_is_indexed_and_ignores_unrelated_malformed_history(tmp_path):
    memory = MemoryStore(str(tmp_path/'memory.db'))
    with memory.connect() as db:
        db.execute("insert into episodic_memory values('retained-malformed','old','not-json','portfolio:the-portal',0,NULL,NULL,'RAW','2020-01-01',NULL)")
        query = """select * from episodic_memory where source=? and
            (case when json_valid(content_json) then
              case when json_type(content_json,'$.event_id')='text'
                   then json_extract(content_json,'$.event_id') end
            end)=? order by created_at,episode_id"""
        plan = ' '.join(row[3] for row in db.execute('explain query plan '+query, ('portfolio:the-portal',event()['event_id'])))
        assert 'USING INDEX episodic_source_event_idx' in plan
    result = memory.record_episode(**episode_fields(event()), idempotency_key=event()['event_id'])
    assert result['idempotency']['state'] == 'CREATED'
    with memory.connect() as db:
        assert db.execute('select count(*) from episodic_memory').fetchone()[0] == 2
        assert db.execute("select content_json from episodic_memory where episode_id='retained-malformed'").fetchone()[0] == 'not-json'


@pytest.fixture
def custody_validator_fixture(monkeypatch):
    """Storage-boundary fixture only; real pinned-schema tests belong to the adapter."""
    def validate(envelope, canonical):
        if set(envelope) != {'contract_version','schema_sha256','raw'}:
            raise ValueError('fixture invalid envelope')
        if not isinstance(envelope['raw'], bytes) or json.loads(envelope['raw']) != canonical:
            raise ValueError('fixture mismatched original')
        return {'contract_version':envelope['contract_version'],'schema_sha256':envelope['schema_sha256'],
                'original_sha256':hashlib.sha256(envelope['raw']).hexdigest(),
                'original_source':canonical['source'],'canonical_source':canonical['source'],'adapter_version':'fixture-only'}
    monkeypatch.setitem(sys.modules, 'app.portfolio_event_compat', SimpleNamespace(validate_original_envelope=validate))


def original_fixture(value=None):
    return {'contract_version':'2.0.0','schema_sha256':'a'*64,'raw':json.dumps(value or event(),indent=2).encode()}


def test_original_custody_store_preserves_exact_bytes_and_rejects_reformatted_replay(tmp_path, custody_validator_fixture):
    fabric = EventFabric(str(tmp_path/'events.db'))
    envelope = original_fixture()
    first = fabric.ingest(event(), original_envelope=envelope)
    original = fabric.original_envelope_record(event()['event_id'])
    assert original['original_bytes'] == envelope['raw']
    assert original['original_sha256'] == hashlib.sha256(envelope['raw']).hexdigest()
    assert original['canonical_source'] == event()['source']
    assert 'NOT_AUTHORITY' in first['original_envelope_receipt']['custody_scope']
    assert fabric.ingest(event(), original_envelope=envelope)['inserted'] is False
    for changed in [
        {**envelope,'raw':json.dumps(event(),separators=(',',':')).encode()},
        {**envelope,'contract_version':'3.0.0'},
        {**envelope,'schema_sha256':'b'*64},
    ]:
        with pytest.raises(ValueError, match='conflicts with retained'):
            fabric.ingest(event(), original_envelope=changed)
    assert fabric.original_envelope_record(event()['event_id']) == original
    assert len(fabric.memory.recent_episodes()) == 1


def test_original_and_inbox_share_atomic_commit_before_projection(tmp_path, custody_validator_fixture):
    fabric = EventFabric(str(tmp_path/'events.db'))
    with fabric.connect() as db:
        db.execute("create trigger reject_original before insert on portfolio_event_originals begin select raise(ABORT,'fixture original fault'); end")
    with pytest.raises(sqlite3.IntegrityError, match='fixture original fault'):
        fabric.ingest(event(), original_envelope=original_fixture())
    assert fabric.recent() == [] and fabric.memory.recent_episodes() == []
    assert fabric.original_envelope_record(event()['event_id']) is None
    with fabric.connect() as db:
        assert db.execute('select count(*) from event_projections').fetchone()[0] == 0


def test_optional_validator_rejection_precedes_inbox_data_writes(tmp_path, custody_validator_fixture):
    fabric = EventFabric(str(tmp_path/'events.db'))
    with pytest.raises(ValueError, match='fixture mismatched original'):
        fabric.ingest(event(), original_envelope=original_fixture({**event(),'payload':{'changed':True}}))
    assert fabric.recent() == [] and fabric.memory.recent_episodes() == []


def test_legacy_wire_cannot_be_backfilled_from_replay(tmp_path, custody_validator_fixture):
    fabric = EventFabric(str(tmp_path/'events.db'))
    first = fabric.ingest(event())
    assert 'original_envelope_receipt' not in first
    assert fabric.original_envelope_record(event()['event_id']) is None
    before = fabric.memory.recent_episodes()
    with pytest.raises(ValueError, match='ORIGINAL_WIRE_UNKNOWN'):
        fabric.ingest(event(), original_envelope=original_fixture())
    assert fabric.original_envelope_record(event()['event_id']) is None
    assert fabric.memory.recent_episodes() == before
    assert fabric.ingest(event())['projected']
