-- Run as migration owner, never as the runtime role. Transactional and additive.
BEGIN;
SELECT pg_advisory_xact_lock(782316);
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS orqevia;
CREATE TABLE IF NOT EXISTS orqevia.schema_migrations (
  version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS orqevia.document_versions (
  owner_id text NOT NULL CHECK (owner_id ~ '^[a-f0-9]{64}$'),
  document_id text NOT NULL CHECK (document_id ~ '^[a-f0-9]{64}$'),
  source text NOT NULL CHECK (length(source) BETWEEN 1 AND 180),
  version integer NOT NULL CHECK (version > 0),
  bytes integer NOT NULL CHECK (bytes BETWEEN 1 AND 8388608),
  origin text NOT NULL DEFAULT 'AUTHORIZED_WORKSPACE_UPLOAD',
  indexed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, document_id), UNIQUE (owner_id, source, version)
);
CREATE TABLE IF NOT EXISTS orqevia.document_chunks (
  owner_id text NOT NULL,
  document_id text NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  page integer,
  content text NOT NULL CHECK (length(content) BETWEEN 1 AND 800),
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[a-f0-9]{64}$'),
  embedding vector(384) NOT NULL,
  embedding_model text NOT NULL CHECK (embedding_model = 'sentence-transformers/all-MiniLM-L6-v2'),
  dimensions integer NOT NULL CHECK (dimensions = 384),
  indexed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, document_id, ordinal),
  FOREIGN KEY (owner_id, document_id) REFERENCES orqevia.document_versions(owner_id, document_id)
);
CREATE TABLE IF NOT EXISTS orqevia.observations (
  event_id text PRIMARY KEY,
  kind text NOT NULL,
  source text NOT NULL,
  scope text NOT NULL CHECK (scope = 'PUBLIC_REFERENCE'),
  position geometry(Point,4326) NOT NULL,
  payload jsonb NOT NULL,
  provenance jsonb NOT NULL,
  observed_at timestamptz NOT NULL,
  ingested_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ST_X(position) BETWEEN -180 AND 180 AND ST_Y(position) BETWEEN -90 AND 90)
);
CREATE INDEX IF NOT EXISTS observations_geometry_gist ON orqevia.observations USING gist(position);
CREATE INDEX IF NOT EXISTS observations_geography_gist ON orqevia.observations USING gist((position::geography));
CREATE INDEX IF NOT EXISTS observations_source_time ON orqevia.observations(source,observed_at,event_id);
ALTER TABLE orqevia.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE orqevia.document_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE orqevia.document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE orqevia.document_chunks FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_policies WHERE schemaname='orqevia' AND tablename='document_versions' AND policyname='owner_isolation') THEN
 CREATE POLICY owner_isolation ON orqevia.document_versions USING (owner_id = current_setting('orqevia.owner_id',true)) WITH CHECK (owner_id = current_setting('orqevia.owner_id',true));
 END IF;
 IF NOT EXISTS (SELECT FROM pg_policies WHERE schemaname='orqevia' AND tablename='document_chunks' AND policyname='owner_isolation') THEN
 CREATE POLICY owner_isolation ON orqevia.document_chunks USING (owner_id = current_setting('orqevia.owner_id',true)) WITH CHECK (owner_id = current_setting('orqevia.owner_id',true));
 END IF;
END $$;
-- Existing runtime role provisioned separately, with no superuser, BYPASSRLS or DDL.
-- GRANT USAGE ON SCHEMA orqevia TO <runtime_role>;
-- GRANT SELECT, INSERT, UPDATE ON orqevia.document_versions, orqevia.document_chunks,
--     orqevia.observations TO <runtime_role>;
-- GRANT SELECT ON orqevia.schema_migrations TO <runtime_role>;
INSERT INTO orqevia.schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
COMMIT;
