-- +goose Up
CREATE TABLE onec_plan_versions (
    company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id text NOT NULL,
    direction text NOT NULL CHECK (direction IN ('in', 'out')),
    version bigint NOT NULL,
    payload jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, source_id, external_id, direction, version)
);

-- +goose Down
DROP TABLE onec_plan_versions;
