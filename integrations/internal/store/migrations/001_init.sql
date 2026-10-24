CREATE TABLE IF NOT EXISTS actual_operations (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  external_id text NOT NULL,
  dedup_key text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, external_id),
  UNIQUE (company_id, dedup_key)
);
CREATE TABLE IF NOT EXISTS planned_events (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  external_id text NOT NULL,
  version bigint NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, external_id)
);
CREATE TABLE IF NOT EXISTS import_batches (
  id bigserial PRIMARY KEY,
  company_id text NOT NULL,
  import_id text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_import_batches_company ON import_batches (company_id, id);
CREATE TABLE IF NOT EXISTS counterparties (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  external_id text NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, external_id)
);
CREATE TABLE IF NOT EXISTS risk_signals (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  external_id text NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, external_id)
);
CREATE TABLE IF NOT EXISTS source_connections (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  connection_id text NOT NULL,
  config jsonb NOT NULL,
  status text NOT NULL,
  cursor text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, connection_id)
);
CREATE TABLE IF NOT EXISTS sync_runs (
  id bigserial PRIMARY KEY,
  company_id text NOT NULL,
  source_kind text NOT NULL,
  status text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  error_code text
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_company ON sync_runs (company_id, id);
