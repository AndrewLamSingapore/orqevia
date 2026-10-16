"""Explicit, isolated development setup and real integration tests.

Requires a running deploy/geospatial/compose.yml project, private password file,
psycopg, repository test dependencies and locally cached MiniLM. No production
connection URL is accepted. Never prints credentials or database exceptions.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--development',action='store_true',required=True)
    args=parser.parse_args()
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    root=Path(__file__).resolve().parents[1]
    passwordfile=Path(os.environ['ORQEVIA_DEV_DB_PASSWORD_FILE']).resolve()
    if passwordfile.is_relative_to(root):raise ValueError('Private password file must be outside source')
    work=passwordfile.parent
    runtimefile=work/'runtime-db-password'
    if not runtimefile.exists():
        with runtimefile.open('x',encoding='utf8') as output:output.write(secrets.token_hex(32))
    admin=make_conninfo(host='127.0.0.1',port=55439,dbname='orqevia_dev',user='migration_owner',password=passwordfile.read_text())
    runtime=make_conninfo(host='127.0.0.1',port=55439,dbname='orqevia_dev',user='orqevia_runtime',password=runtimefile.read_text())
    try:
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute((root/'deploy/geospatial/001-intelligence.sql').read_text(),prepare=False)
        with psycopg.connect(admin) as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname='orqevia_runtime'").fetchone():
                conn.execute(sql.SQL('CREATE ROLE orqevia_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}').format(sql.Literal(runtimefile.read_text())))
            conn.execute('GRANT CONNECT ON DATABASE orqevia_dev TO orqevia_runtime')
            conn.execute('GRANT USAGE ON SCHEMA orqevia TO orqevia_runtime')
            conn.execute('GRANT SELECT,INSERT,UPDATE ON orqevia.document_versions,orqevia.document_chunks,orqevia.observations TO orqevia_runtime')
            conn.execute('GRANT SELECT ON orqevia.schema_migrations TO orqevia_runtime')
    except Exception:
        sys.exit('Development database setup failed; details suppressed to protect credentials')
    env=os.environ.copy()
    data=work/'qualification-data';data.mkdir(exist_ok=True)
    env.update(ORQEVIA_TEST_DSN=runtime,ORQEVIA_TEST_ADMIN_DSN=admin,ORQEVIA_TEST_DATA=str(data),
        ORQEVIA_DATA_DIR=str(data),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    code=subprocess.call([sys.executable,'-B','-m','pytest','tests/test_postgres_intelligence.py','-q','--tb=short','--junitxml='+str(work/'postgres-tests.xml')],cwd=root,env=env)
    with psycopg.connect(admin) as conn:
        conn.execute("DELETE FROM orqevia.observations WHERE event_id LIKE 'test-controlled-%%' AND provenance->>'test_fixture'='true'")
    return code

if __name__=='__main__':sys.exit(main())
