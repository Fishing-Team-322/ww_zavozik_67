-- +goose Up
ALTER TABLE users ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','blocked'));
ALTER TABLE users ADD COLUMN last_login_at timestamptz;
ALTER TABLE companies ADD COLUMN data_revision bigint NOT NULL DEFAULT 0;
ALTER TABLE operations ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE sources ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE sources ADD COLUMN enabled boolean NOT NULL DEFAULT true;
ALTER TABLE recurring_patterns ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE recurring_patterns ADD COLUMN active boolean NOT NULL DEFAULT true;
ALTER TABLE planned_events ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE scenarios ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE alerts ADD COLUMN extra jsonb NOT NULL DEFAULT '{}';
ALTER TABLE alerts ADD COLUMN kind text NOT NULL DEFAULT 'gap_risk';
ALTER TABLE audit_log ADD COLUMN detail jsonb NOT NULL DEFAULT '{}';
ALTER TABLE forecast_runs ADD COLUMN revision bigint NOT NULL DEFAULT 0;
ALTER TABLE forecast_runs ADD COLUMN payload jsonb NOT NULL DEFAULT '{}';
CREATE UNIQUE INDEX event_occurrence ON planned_events(company_id,(extra->>'occurrence_key')) WHERE extra ? 'occurrence_key';

-- New product documents have a versioned, validated API schema. Existing financial
-- facts/events/patterns/sources continue using their original normalized tables.
CREATE TABLE product_documents (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 company_id uuid REFERENCES companies(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('invoice','contract','action','signal','import','model_quality','classifier_quality','drift')),
 data jsonb NOT NULL CHECK(jsonb_typeof(data)='object'),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(company_id IS NOT NULL OR kind IN ('model_quality','classifier_quality','drift'))
);
CREATE INDEX product_documents_scope ON product_documents(company_id,kind,created_at,id);
CREATE TABLE product_uploads (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 filename text NOT NULL,
 format text NOT NULL,
 content bytea NOT NULL,
 mapping jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE product_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 company_id uuid REFERENCES companies(id) ON DELETE CASCADE,
 actor_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('import','sync','export','recompute','retrain')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','failed')),
 progress double precision NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
 payload jsonb NOT NULL DEFAULT '{}',
 result jsonb,
 error text,
 attempts int NOT NULL DEFAULT 0,
 locked_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz
);
CREATE INDEX product_jobs_queue ON product_jobs(status,created_at);
CREATE INDEX product_jobs_actor ON product_jobs(actor_id,created_at);
CREATE UNIQUE INDEX product_jobs_recompute_pending ON product_jobs(company_id) WHERE kind='recompute' AND status='queued';
CREATE TABLE product_downloads (
 job_id uuid PRIMARY KEY REFERENCES product_jobs(id) ON DELETE CASCADE,
 filename text NOT NULL,
 mime text NOT NULL,
 content bytea NOT NULL
);
CREATE TABLE category_corrections (
 id bigserial PRIMARY KEY,
 company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 operation_id text NOT NULL,
 category text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE category_rules (
 company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 counterparty_key text NOT NULL,
 category text NOT NULL,
 PRIMARY KEY(company_id,counterparty_key)
);

-- +goose Down
DROP TABLE category_rules,category_corrections,product_downloads,product_jobs,product_uploads,product_documents;
DROP INDEX event_occurrence;
ALTER TABLE forecast_runs DROP COLUMN revision,DROP COLUMN payload;
ALTER TABLE audit_log DROP COLUMN detail;
ALTER TABLE alerts DROP COLUMN kind,DROP COLUMN extra;
ALTER TABLE planned_events DROP COLUMN extra;
ALTER TABLE scenarios DROP COLUMN extra;
ALTER TABLE recurring_patterns DROP COLUMN active,DROP COLUMN extra;
ALTER TABLE sources DROP COLUMN enabled,DROP COLUMN extra;
ALTER TABLE companies DROP COLUMN data_revision;
ALTER TABLE operations DROP COLUMN extra;
ALTER TABLE users DROP COLUMN status,DROP COLUMN last_login_at;
