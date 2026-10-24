CREATE TABLE IF NOT EXISTS marketplace_entries (
  company_id text NOT NULL,
  source_kind text NOT NULL,
  external_id text NOT NULL,
  version bigint NOT NULL,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, source_kind, external_id)
);
