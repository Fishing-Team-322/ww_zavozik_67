-- +goose Up
-- Older builds projected inferred schedules before user confirmation. Remove
-- only their unpaid automatic projections, preserving paid history and edits.
WITH removed AS (
 DELETE FROM planned_events e USING recurring_patterns p
 WHERE e.company_id=p.company_id AND e.extra->>'recurring_id'=p.id::text
  AND e.source_kind='recurring' AND p.confirmed IS NOT TRUE
  AND e.status IN ('expected','missed') AND e.matched_operation_id IS NULL
  AND COALESCE((e.extra->>'user_override')::boolean,false)=false
 RETURNING e.company_id
), changed AS (
 UPDATE companies SET data_revision=data_revision+1,updated_at=clock_timestamp()
 WHERE id IN (SELECT company_id FROM removed)
 RETURNING id
)
INSERT INTO product_jobs(company_id,actor_id,kind)
SELECT c.id,m.user_id,'recompute' FROM changed c
JOIN LATERAL (SELECT user_id FROM memberships WHERE company_id=c.id AND role='owner' ORDER BY user_id LIMIT 1) m ON true
ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING;

-- +goose Down
-- Generated unpaid occurrences are rebuilt from confirmed patterns as needed.
SELECT 1;
