"""Real optional PostgreSQL integration; no mocked database or embedding model.

Set ORQEVIA_TEST_DSN to a disposable migrated DB with a non-bypass runtime role.
Do not point at production. No tests create extensions or alter production state.
"""
import hashlib
import math
import os
import uuid
from datetime import datetime,timezone
from pathlib import Path

import pytest

from app.postgres_intelligence import Database,DatabaseUnavailable,PostgresKnowledgeEngine,PostgresObservationStore,vector

pytestmark=pytest.mark.skipif(not os.getenv('ORQEVIA_TEST_DSN'),reason='Real disposable PostgreSQL URL required')

@pytest.fixture(scope='module')
def database():return Database(os.environ['ORQEVIA_TEST_DSN'])

@pytest.fixture(scope='module')
def encoder():
    from app.local_knowledge import KnowledgeEngine
    return KnowledgeEngine(Path(os.environ['ORQEVIA_TEST_DATA']))._encoder()

@pytest.fixture
def engine(tmp_path,database,encoder):
    return PostgresKnowledgeEngine(tmp_path,owner=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),database=database,encoder=encoder)

@pytest.fixture
def observation(database):
    record={'event_id':'test-controlled-'+uuid.uuid4().hex,'kind':'earthquake','source':'USGS',
        'source_url':'https://earthquake.usgs.gov/','location':{'lat':1.3,'lon':103.8},
        'observed_at':datetime.now(timezone.utc).isoformat(),'ingested_at':datetime.now(timezone.utc).isoformat(),
        'place':'CONTROLLED TEST FIXTURE, NOT A REAL EVENT','magnitude':1}
    return PostgresObservationStore(database),record

def test_extensions_and_least_privilege(database):
    with database.transaction() as conn:
        extensions=conn.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector','postgis')").fetchall()
        assert {r['extname'] for r in extensions}=={'vector','postgis'}
        assert not conn.execute("SELECT has_schema_privilege(current_user,'orqevia','CREATE') AS value").fetchone()['value']

def test_embedding_dimensions_and_normalization(engine):
    output=engine._embed(['Grounded geospatial retrieval'])
    assert output.shape==(1,384)
    assert math.isclose(float((output[0]**2).sum()),1,abs_tol=.001)

def test_vector_rejects_wrong_dimensions_and_nan():
    for value in [[1]*3,[float('nan')]*384,[0]*384]:
        with pytest.raises(ValueError):vector(value)

def test_ingestion_similarity_and_evidence(engine):
    receipt=engine.ingest('public-reference.txt',b'Singapore is an island city in Southeast Asia. Canberra is the capital of Australia.')
    result=engine.retrieve('Where is Singapore?')
    assert receipt['status']=='INDEXED' and result['status']=='RETRIEVED'
    hit=result['results'][0]
    assert hit['document_id']==receipt['document_id'] and 'Southeast Asia' in hit['passage']
    assert hashlib.sha256(hit['passage'].encode()).hexdigest()==hit['sha256']

def test_version_management_and_duplicate(engine):
    first=engine.ingest('operational.txt',b'The operational color is red.')
    assert engine.ingest('operational.txt',b'The operational color is red.')['status']=='UNCHANGED'
    second=engine.ingest('operational.txt',b'The operational color is blue.')
    assert second['version']==2
    assert engine.retrieve('operational color')['results'][0]['document_id']==second['document_id']
    assert engine.retrieve('operational color',document_ids=[first['document_id']])['results']==[]
    assert len(engine.list_documents()['documents'])==2

def test_reindex_preserves_versions(engine):
    engine.ingest('reindex.txt',b'PostGIS stores geographic coordinates and geometry.')
    before=engine.retrieve('geographic geometry')['results'][0]
    assert engine.reindex()['chunks']==1
    assert engine.retrieve('geographic geometry')['results'][0]['sha256']==before['sha256']

def test_cross_account_isolation_and_rls(engine,tmp_path):
    receipt=engine.ingest('private.txt',b'Private ownership isolation is mandatory for confidential documents.')
    other=PostgresKnowledgeEngine(tmp_path,owner=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),database=engine.database,encoder=engine.encoder)
    assert not other.list_documents()['documents']
    assert not other.retrieve('confidential documents',document_ids=[receipt['document_id']])['results']
    with engine.database.transaction(other.owner) as conn:
        assert conn.execute('SELECT count(*) AS n FROM orqevia.document_chunks WHERE owner_id=%s',(engine.owner,)).fetchone()['n']==0
    with engine.database.transaction() as conn:
        assert conn.execute('SELECT count(*) AS n FROM orqevia.document_chunks').fetchone()['n']==0

def test_validation_preserves_documents(engine):
    for name,raw in [('../bad.txt',b'x'),('script.exe',b'x'),('empty.txt',b'')]:
        with pytest.raises(ValueError):engine.ingest(name,raw)
    assert not engine.list_documents()['documents']

def test_query_validation(engine):
    for args in [('',),('test',0),('test',3,['not-a-hash'])]:
        with pytest.raises(ValueError):engine.retrieve(*args)

def test_postgis_insertion_provenance_and_upsert(observation):
    store,r=observation
    assert store.upsert(r,{'test_fixture':True})
    assert not store.upsert(r,{'test_fixture':True})
    assert store.get(r['event_id'])['provenance']=={'test_fixture':True}

def test_coordinate_and_private_source_rejection(observation):
    store,r=observation
    for lat in [91,float('nan'),float('inf')]:
        with pytest.raises(ValueError):store.upsert({**r,'location':{'lat':lat,'lon':103}}, {})
    with pytest.raises(ValueError):store.upsert({**r,'source':'PRIVATE'}, {})

def test_bbox_distance_and_filtering(observation):
    store,r=observation;store.upsert(r,{'test_fixture':True})
    assert any(x['event_id']==r['event_id'] for x in store.query(min_lat=1,max_lat=2,min_lon=103,max_lon=104))
    assert any(x['event_id']==r['event_id'] for x in store.query(min_lat=1))
    assert any(x['event_id']==r['event_id'] for x in store.query(lat=1.3,lon=103.8,radius_km=1))
    assert all(x['event_id']!=r['event_id'] for x in store.query(lat=-30,lon=-90,radius_km=1))
    with pytest.raises(ValueError):store.query(source="USGS' OR TRUE--")

def test_pagination_time_and_spatial_indexes(observation,database):
    store,r=observation;store.upsert(r,{'test_fixture':True})
    assert len(store.query(limit=1,offset=0,source='USGS'))<=1
    assert not store.query(min_time='2099-01-01T00:00:00+00:00')
    with database.transaction() as conn:
        indexes=conn.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='orqevia' AND tablename='observations'").fetchall()
        assert sum('USING gist' in row['indexdef'] for row in indexes)==2
    assert store.regions()

def test_geojson_api_and_authenticated_service(monkeypatch,tmp_path,observation):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.orqevia import intelligence_api as api
    from app.orqevia.security import install
    store,r=observation;store.upsert(r,{'test_fixture':True})
    monkeypatch.setattr(api,'OBSERVATIONS',store)
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path));monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','controlled-service-authentication')
    app=FastAPI();app.include_router(api.router);install(app);client=TestClient(app)
    path='/api/orqevia/intelligence/geo/features'
    assert client.get(path).status_code==401
    headers={'Authorization':'Bearer controlled-service-authentication'}
    result=client.get(path,headers=headers).json()
    assert result['type']=='FeatureCollection' and result['scope']=='PUBLIC_REFERENCE'
    assert client.get(path+'?min_lat=90&max_lat=-90',headers=headers).status_code==422

def test_runtime_superuser_is_rejected():
    if not os.getenv('ORQEVIA_TEST_ADMIN_DSN'):pytest.skip('Admin test URL not supplied')
    with pytest.raises(DatabaseUnavailable):
        with Database(os.environ['ORQEVIA_TEST_ADMIN_DSN']).transaction():pass
