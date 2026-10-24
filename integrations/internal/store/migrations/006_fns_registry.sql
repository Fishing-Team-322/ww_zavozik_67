CREATE TABLE IF NOT EXISTS fns_registry_current (
 company_id text NOT NULL,
 source_kind text NOT NULL,
 ogrn text NOT NULL,
 inn text NOT NULL,
 actual_at date NOT NULL,
 content_hash text NOT NULL,
 version bigint NOT NULL,
 payload jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(company_id,source_kind,ogrn)
);
CREATE INDEX IF NOT EXISTS idx_fns_registry_inn ON fns_registry_current(company_id,inn);
CREATE TABLE IF NOT EXISTS fns_registry_history (
 id bigserial PRIMARY KEY,
 company_id text NOT NULL,
 source_kind text NOT NULL,
 ogrn text NOT NULL,
 inn text NOT NULL,
 actual_at date NOT NULL,
 content_hash text NOT NULL,
 payload jsonb NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(company_id,source_kind,ogrn,content_hash)
);
CREATE INDEX IF NOT EXISTS idx_fns_registry_history_lookup ON fns_registry_history(company_id,inn,id DESC);
CREATE TABLE IF NOT EXISTS fns_dataset_state (
 company_id text NOT NULL,
 dataset_id text NOT NULL,
 version text NOT NULL,
 source_url text NOT NULL,
 published_at date NOT NULL,
 dataset_as_of date NOT NULL,
 retrieved_at timestamptz NOT NULL,
 files integer NOT NULL,
 documents integer NOT NULL,
 matches integer NOT NULL,
 PRIMARY KEY(company_id,dataset_id)
);
CREATE TABLE IF NOT EXISTS fns_dataset_runs (
 id bigserial PRIMARY KEY,
 company_id text NOT NULL,
 dataset_id text NOT NULL,
 status text NOT NULL,
 version text,
 error_code text,
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fns_dataset_runs_company ON fns_dataset_runs(company_id,dataset_id,id DESC);
