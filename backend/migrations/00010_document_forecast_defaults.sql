-- +goose Up
-- Missing means the caller never opted out. Preserve an explicit false.
WITH changed AS (
 UPDATE product_documents SET data=data||'{"additional":true,"_default_forecast_v10":true}'::jsonb,
 updated_at=clock_timestamp()
 WHERE kind IN ('invoice','contract') AND NOT data ? 'additional'
 RETURNING id,company_id
), projections AS (
 UPDATE planned_events e SET extra=e.extra||'{"additional":true}'::jsonb
 FROM changed d WHERE e.company_id=d.company_id AND e.extra->>'document_id'=d.id::text
 RETURNING e.company_id
), revisions AS (
 UPDATE companies SET data_revision=data_revision+1
 WHERE id IN (SELECT company_id FROM changed) RETURNING id
)
INSERT INTO product_jobs(company_id,actor_id,kind)
SELECT DISTINCT r.id,m.user_id,'recompute' FROM revisions r
JOIN memberships m ON m.company_id=r.id AND m.role='owner'
ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING;

-- +goose Down
UPDATE planned_events e SET extra=e.extra-'additional'
FROM product_documents d WHERE d.kind IN ('invoice','contract')
AND d.data->>'_default_forecast_v10'='true'
AND e.company_id=d.company_id AND e.extra->>'document_id'=d.id::text;
UPDATE product_documents SET data=data-'additional'-'_default_forecast_v10'
WHERE data->>'_default_forecast_v10'='true';
