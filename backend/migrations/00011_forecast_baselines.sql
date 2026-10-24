-- +goose Up
CREATE TABLE forecast_baselines (
 company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 cache_key text NOT NULL,
 model text NOT NULL,
 request jsonb NOT NULL,
 result jsonb NOT NULL,
 saved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(company_id,cache_key)
);

-- +goose Down
DROP TABLE forecast_baselines;
