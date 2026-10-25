-- +goose Up
-- Repair only unclassified automatic records; preserve every user correction.
WITH changed AS (
 UPDATE operations SET category='owner_loan',category_method='rule',is_internal=true
 WHERE category='other' AND category_method<>'user'
 AND counterparty_name ~* '(учредител|собственник)' AND purpose ~* 'за[еёий]м'
 RETURNING company_id
), touched AS (
 UPDATE companies SET data_revision=data_revision+1 WHERE id IN (SELECT company_id FROM changed) RETURNING id
)
INSERT INTO product_jobs(company_id,actor_id,kind)
SELECT t.id,m.user_id,'recompute' FROM touched t JOIN memberships m ON m.company_id=t.id AND m.role='owner'
ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING;

UPDATE alerts a SET read=true,extra=a.extra||'{"resolved":true}'::jsonb
WHERE a.kind='missed_payment' AND EXISTS (
 SELECT 1 FROM planned_events e WHERE e.company_id=a.company_id
 AND e.id::text=a.extra->'ref'->>'id' AND e.status IN ('received','cancelled')
);

-- +goose Down
-- Classifications and resolved financial history are intentionally retained.
