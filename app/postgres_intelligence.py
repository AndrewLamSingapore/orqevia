"""Opt-in PostgreSQL adapters; no automatic migration or legacy data mutation."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from .local_knowledge import (KnowledgeEngine, EMBEDDING_MODEL, MAX_UPLOAD,
    MAX_CHUNKS, chunks, now, sha, worker_options, worker_python)


class DatabaseUnavailable(RuntimeError):
    """Sanitized dependency failure: never include DSN, SQL values or secrets."""


class Database:
    def __init__(self, dsn=None):
        self.dsn = dsn or os.getenv('ORQEVIA_DATABASE_URL', '')
        if not self.dsn:
            raise DatabaseUnavailable('PostgreSQL connection is not configured')

    @contextmanager
    def transaction(self, owner=None):
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.dsn, connect_timeout=5, row_factory=dict_row) as conn:
                role = conn.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
                if role['rolsuper'] or role['rolbypassrls']:
                    raise DatabaseUnavailable('Runtime database role must not bypass row security')
                conn.execute("SET LOCAL statement_timeout = '10s'")
                if owner is not None:
                    if not re.fullmatch('[a-f0-9]{64}', owner):
                        raise ValueError('Invalid owner scope')
                    conn.execute("SELECT set_config('orqevia.owner_id',%s,true)", (owner,))
                yield conn
        except (ImportError, OSError) as exc:
            raise DatabaseUnavailable('PostgreSQL dependency unavailable') from None
        except Exception as exc:
            if type(exc).__module__.startswith('psycopg'):
                raise DatabaseUnavailable('PostgreSQL operation failed; existing data preserved') from None
            raise


def vector(value):
    items = [float(x) for x in value]
    if len(items) != 384 or not all(math.isfinite(x) for x in items):
        raise ValueError('Embedding must have 384 finite dimensions')
    norm = math.sqrt(sum(x*x for x in items))
    if not 0.999 <= norm <= 1.001:
        raise ValueError('Embedding must be normalized and nonzero')
    return '[' + ','.join(str(x) for x in items) + ']'


class PostgresKnowledgeEngine(KnowledgeEngine):
    """Same extraction, embedding and answer contract as the retained FAISS engine."""
    def __init__(self, root, *, owner, database=None, **kwargs):
        super().__init__(root, **kwargs)
        if not re.fullmatch('[a-f0-9]{64}', owner):
            raise ValueError('A bound owner scope is required')
        self.owner = owner
        self.database = database or Database()

    def list_documents(self):
        with self.database.transaction(self.owner) as conn:
            rows = conn.execute('SELECT document_id,document_id AS sha256,source,version,bytes,origin,indexed_at AS ingested_at FROM orqevia.document_versions WHERE owner_id=%s ORDER BY source,version', (self.owner,)).fetchall()
        return {'documents': rows}

    def health(self):
        try:
            with self.database.transaction(self.owner) as conn:
                row = conn.execute('SELECT count(*) AS chunks,count(DISTINCT document_id) AS documents FROM orqevia.document_chunks WHERE owner_id=%s', (self.owner,)).fetchone()
            index = {'status':'READY', **row, 'dimensions':384}
        except DatabaseUnavailable:
            index = {'status':'UNAVAILABLE'}
        return {'service':'ORQEVIA knowledge','backend':'pgvector','index':index,
                'embedding_model':EMBEDDING_MODEL,'local_only':True,'observed_at':now()}

    def ingest(self, filename, raw):
        name = Path(filename).name
        suffix = Path(filename).suffix.lower()
        if name != filename or '/' in filename or '\\' in filename or not 1 <= len(name) <= 180 or any(ord(c)<32 for c in name):
            raise ValueError('Invalid document name')
        if suffix not in {'.txt','.md','.pdf','.docx'} or not 0 < len(raw) <= MAX_UPLOAD:
            raise ValueError('A bounded PDF, DOCX, TXT or Markdown document is required')
        digest = sha(raw)
        # Existing upload bytes are immutable and preserved. Owner namespace keeps
        # identical names/content from crossing private parser-input boundaries.
        target = self.documents / 'postgres-uploads' / self.owner / (digest+suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            uploads=target.parent
            if not target.exists() and sum(p.stat().st_size for p in uploads.iterdir() if p.is_file())+len(raw)>512*1024*1024:
                raise ValueError('Preserved parser input budget exceeded')
            with self.database.transaction(self.owner) as conn:
                existing = conn.execute('SELECT document_id FROM orqevia.document_versions WHERE owner_id=%s AND document_id=%s',(self.owner,digest)).fetchone()
                if existing:
                    return {'status':'UNCHANGED','document_id':digest,'duplicate_prevented':True}
            if not target.exists():
                with target.open('xb') as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
            if self.extractor:
                pages = self.extractor(target)
            else:
                parsed = subprocess.run([worker_python(),'-B','-m','app.local_document_extract',str(target)],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding='utf8', timeout=20, **worker_options())
                if parsed.returncode or len(parsed.stdout)>4_000_000:
                    raise ValueError('Bounded document extraction failed')
                pages = json.loads(parsed.stdout)
            records = [(part,page) for text,page in pages for part in chunks(text)]
            if not records or len(records)>MAX_CHUNKS:
                raise ValueError('Document is empty or exceeds chunk budget')
            vectors = [vector(v) for v in self._embed([r[0] for r in records])]
            if len(vectors)!=len(records):
                raise ValueError('Embedding count mismatch')
            with self.database.transaction(self.owner) as conn:
                # Serialize version allocation and budget checks across workers.
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(self.owner,))
                if conn.execute('SELECT 1 FROM orqevia.document_versions WHERE owner_id=%s AND document_id=%s',(self.owner,digest)).fetchone():
                    return {'status':'UNCHANGED','document_id':digest,'duplicate_prevented':True}
                budget = conn.execute('SELECT count(*) AS documents,COALESCE(sum(bytes),0) AS bytes FROM orqevia.document_versions WHERE owner_id=%s',(self.owner,)).fetchone()
                count = conn.execute('SELECT count(*) AS n FROM orqevia.document_chunks WHERE owner_id=%s',(self.owner,)).fetchone()['n']
                if budget['documents']>=2000 or budget['bytes']+len(raw)>512*1024*1024 or count+len(records)>MAX_CHUNKS:
                    raise ValueError('Document storage budget exceeded')
                version = conn.execute('SELECT COALESCE(max(version),0)+1 AS n FROM orqevia.document_versions WHERE owner_id=%s AND source=%s',(self.owner,name)).fetchone()['n']
                conn.execute('INSERT INTO orqevia.document_versions(owner_id,document_id,source,version,bytes) VALUES(%s,%s,%s,%s,%s)',(self.owner,digest,name,version,len(raw)))
                with conn.cursor() as cursor:
                    cursor.executemany('INSERT INTO orqevia.document_chunks(owner_id,document_id,ordinal,page,content,content_sha256,embedding,embedding_model,dimensions) VALUES(%s,%s,%s,%s,%s,%s,%s::vector,%s,384)',
                        [(self.owner,digest,i,page,text,sha(text.encode()),vectors[i],EMBEDDING_MODEL) for i,(text,page) in enumerate(records)])
            return {'status':'INDEXED','document_id':digest,'version':version,'added_chunks':len(records),'chunks':count+len(records),'backend':'pgvector','duplicate_prevented':False}

    def retrieve(self, question, top_k=3, document_ids=None):
        if not isinstance(question,str) or not 0<len(question.strip())<=4096:
            raise ValueError('A bounded retrieval question is required')
        if type(top_k) is not int or not 1<=top_k<=5:
            raise ValueError('top_k must be between 1 and 5')
        if document_ids is not None and (not isinstance(document_ids,list) or len(document_ids)>50 or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in document_ids)):
            raise ValueError('Invalid document selection')
        query = vector(self._embed([question])[0])
        with self.database.transaction(self.owner) as conn:
            # Ownership and latest version selection happen BEFORE exact ranking.
            rows = conn.execute('''SELECT c.document_id,d.source,d.version,c.page,c.content,c.content_sha256,
                1-(c.embedding <=> %s::vector) AS similarity
                FROM orqevia.document_chunks c JOIN orqevia.document_versions d USING(owner_id,document_id)
                WHERE c.owner_id=%s AND c.embedding_model=%s
                AND (%s::text[] IS NULL OR c.document_id=ANY(%s::text[]))
                AND NOT EXISTS(SELECT 1 FROM orqevia.document_versions newer WHERE newer.owner_id=d.owner_id AND newer.source=d.source AND newer.version>d.version)
                ORDER BY c.embedding <=> %s::vector,c.document_id,c.ordinal LIMIT %s''',
                (query,self.owner,EMBEDDING_MODEL,document_ids,document_ids,query,top_k)).fetchall()
        results=[]
        for row in rows:
            if sha(row['content'].encode())!=row['content_sha256']:
                raise ValueError('Retrieved evidence hash mismatch')
            if row['similarity']<0.20:
                continue
            results.append({'citation':f'[{len(results)+1}]','document_id':row['document_id'],
                'source':row['source'],'document_version':row['version'],'page':row['page'],
                'passage':row['content'],'sha256':row['content_sha256'],'similarity':float(row['similarity']),
                'content_is_authority':False,'instructions_may_execute':False})
        return {'status':'RETRIEVED' if results else 'NO_EVIDENCE','results':results,'embedding_model':EMBEDDING_MODEL,
            'diagnostics':{'backend':'pgvector','metric':'exact cosine','dimensions':384,'owner_filtered':True}}

    def reindex(self):
        with self.lock, self.database.transaction(self.owner) as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(self.owner,))
            rows=conn.execute('SELECT document_id,ordinal,content,content_sha256 FROM orqevia.document_chunks WHERE owner_id=%s ORDER BY document_id,ordinal',(self.owner,)).fetchall()
            if not rows:
                return {'status':'REINDEXED','chunks':0,'previous_versions_preserved':True}
            if any(sha(r['content'].encode())!=r['content_sha256'] for r in rows):
                raise ValueError('Stored chunk integrity mismatch')
            vectors=[vector(v) for v in self._embed([r['content'] for r in rows])]
            with conn.cursor() as cursor:
                cursor.executemany('UPDATE orqevia.document_chunks SET embedding=%s::vector,indexed_at=now() WHERE owner_id=%s AND document_id=%s AND ordinal=%s',
                    [(vectors[i],self.owner,r['document_id'],r['ordinal']) for i,r in enumerate(rows)])
            return {'status':'REINDEXED','chunks':len(rows),'previous_versions_preserved':True}


class PostgresObservationStore:
    """Public-reference scope only; never accepts private observation records."""
    def __init__(self, database=None):
        self.database=database or Database()

    def upsert(self, record, provenance):
        from psycopg.types.json import Jsonb
        from .geospatial import validate_coordinate
        lat,lon=validate_coordinate(record['location']['lat'],record['location']['lon'])
        if not all(math.isfinite(v) for v in (lat,lon)):
            raise ValueError('Finite coordinates required')
        if record.get('source')!='USGS' or not record.get('source_url','').startswith('https://earthquake.usgs.gov/'):
            raise ValueError('Only attributed public USGS observations are supported')
        for field in ('observed_at','ingested_at'):
            parsed=datetime.fromisoformat(record[field].replace('Z','+00:00'))
            if parsed.tzinfo is None:raise ValueError('Timezone-aware observation timestamps required')
        with self.database.transaction() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,1))',(record['event_id'],))
            existing=conn.execute('SELECT 1 FROM orqevia.observations WHERE event_id=%s',(record['event_id'],)).fetchone()
            conn.execute('''INSERT INTO orqevia.observations(event_id,kind,source,scope,position,payload,provenance,observed_at,ingested_at)
                VALUES(%s,%s,%s,'PUBLIC_REFERENCE',ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s,%s)
                ON CONFLICT(event_id) DO UPDATE SET position=excluded.position,payload=excluded.payload,
                provenance=excluded.provenance,observed_at=excluded.observed_at,updated_at=now()''',
                (record['event_id'],record['kind'],record['source'],lon,lat,Jsonb(record),Jsonb(provenance),record['observed_at'],record['ingested_at']))
        return not bool(existing)

    def query(self, *, min_lat=None,max_lat=None,min_lon=None,max_lon=None,min_time=None,max_time=None,
              limit=200,offset=0,source=None,lat=None,lon=None,radius_km=None):
        if type(limit) is not int or not 1<=limit<=500 or type(offset) is not int or not 0<=offset<=100000:
            raise ValueError('Invalid pagination')
        bounds=(min_lat,max_lat,min_lon,max_lon)
        if any(v is not None for v in bounds):
            min_lat=-90 if min_lat is None else min_lat
            max_lat=90 if max_lat is None else max_lat
            min_lon=-180 if min_lon is None else min_lon
            max_lon=180 if max_lon is None else max_lon
            if not all(math.isfinite(v) for v in (min_lat,max_lat,min_lon,max_lon)):raise ValueError('A finite bounding box is required')
            if not -90<=min_lat<=max_lat<=90 or not -180<=min_lon<=max_lon<=180:raise ValueError('Invalid bounding box')
        clauses=["scope='PUBLIC_REFERENCE'"]; params=[]
        if min_lat is not None:
            clauses.append('position && ST_MakeEnvelope(%s,%s,%s,%s,4326)');params.extend([min_lon,min_lat,max_lon,max_lat])
        for value,operator in ((min_time,'>='),(max_time,'<=')):
            if value:
                stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('Timezone required')
                clauses.append('observed_at '+operator+' %s');params.append(stamp)
        if source:
            if source!='USGS':raise ValueError('Unsupported source filter')
            clauses.append('source=%s');params.append(source)
        if any(v is not None for v in (lat,lon,radius_km)):
            if any(v is None or not math.isfinite(v) for v in (lat,lon,radius_km)) or not -90<=lat<=90 or not -180<=lon<=180 or not 0<=radius_km<=40075:
                raise ValueError('Invalid radius query')
            clauses.append('ST_DWithin(position::geography,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)');params.extend([lon,lat,radius_km*1000])
        with self.database.transaction() as conn:
            rows=conn.execute('SELECT payload,provenance FROM orqevia.observations WHERE '+' AND '.join(clauses)+' ORDER BY observed_at DESC,event_id LIMIT %s OFFSET %s',(*params,limit,offset)).fetchall()
        return [{**r['payload'],'provenance':r['provenance']} for r in rows]

    def count(self):
        with self.database.transaction() as conn:
            return conn.execute("SELECT count(*) AS n FROM orqevia.observations WHERE scope='PUBLIC_REFERENCE'").fetchone()['n']

    def get(self,event_id):
        with self.database.transaction() as conn:
            row=conn.execute("SELECT payload,provenance FROM orqevia.observations WHERE event_id=%s AND scope='PUBLIC_REFERENCE'",(event_id,)).fetchone()
        return {**row['payload'],'provenance':row['provenance']} if row else None

    def regions(self):
        with self.database.transaction() as conn:
            return conn.execute("SELECT floor((ST_X(position)+180)/10)::int AS x,floor((ST_Y(position)+90)/10)::int AS y,count(*) AS count FROM orqevia.observations WHERE scope='PUBLIC_REFERENCE' GROUP BY x,y ORDER BY x,y").fetchall()


def knowledge_engine(root):
    backend=os.getenv('ORQEVIA_KNOWLEDGE_BACKEND','faiss')
    if backend=='faiss':return KnowledgeEngine(root)
    if backend!='postgres':raise ValueError('Unknown knowledge backend')
    account=os.getenv('ORQEVIA_OWNER_ACCOUNT','')
    if not account:raise ValueError('A bound owner account is required')
    return PostgresKnowledgeEngine(root,owner=hashlib.sha256(account.encode()).hexdigest())
