-- +goose Up
-- A bank fact remains consumed even if its calendar projection is rebuilt or
-- its source document is deleted. The event ID is an audit reference, not a FK.
CREATE TABLE operation_settlements (
 company_id uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
 operation_id text NOT NULL,
 event_id uuid NOT NULL,
 source_kind text NOT NULL,
 document_id text,
 matched_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(company_id,operation_id),
 FOREIGN KEY(company_id,operation_id) REFERENCES operations(company_id,id) ON DELETE CASCADE
);
-- Restore identity that older projections kept only on the source document
-- (or in the pattern's JSON), before future reconciliation uses it.
UPDATE recurring_patterns SET counterparty_inn=extra->>'counterparty_inn'
WHERE counterparty_inn IS NULL AND NULLIF(extra->>'counterparty_inn','') IS NOT NULL;
UPDATE planned_events e SET extra=e.extra||jsonb_build_object('counterparty_inn',d.data->>'counterparty_inn')
FROM product_documents d
WHERE e.company_id=d.company_id AND e.extra->>'document_id'=d.id::text
 AND e.source_kind IN ('invoice','contract') AND d.kind IN ('invoice','contract')
 AND NULLIF(d.data->>'counterparty_inn','') IS NOT NULL;
UPDATE planned_events e SET extra=e.extra||jsonb_build_object('counterparty_inn',p.counterparty_inn)
FROM recurring_patterns p
WHERE e.company_id=p.company_id AND e.extra->>'recurring_id'=p.id::text
 AND NULLIF(p.counterparty_inn,'') IS NOT NULL;
INSERT INTO operation_settlements(company_id,operation_id,event_id,source_kind,document_id)
SELECT DISTINCT ON (e.company_id,e.matched_operation_id)
 e.company_id,e.matched_operation_id,e.id,e.source_kind,e.extra->>'document_id'
FROM planned_events e JOIN operations o
 ON o.company_id=e.company_id AND o.id=e.matched_operation_id
WHERE e.matched_operation_id IS NOT NULL
ORDER BY e.company_id,e.matched_operation_id,e.created_at,e.id;

-- +goose Down
DROP TABLE operation_settlements;
