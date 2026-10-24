-- +goose Up
-- XLSX is a file format. The published API source kind is "excel".
-- Preserve operation IDs, facts, source IDs and settlement references.
UPDATE sources SET kind='excel' WHERE kind='xlsx';
UPDATE operations SET extra=jsonb_set(extra,'{source}','"excel"'::jsonb)
WHERE extra->>'source'='xlsx';
UPDATE product_documents SET data=jsonb_set(data,'{source,kind}','"excel"'::jsonb)
WHERE kind='import' AND data->'source'->>'kind'='xlsx';

-- +goose Down
-- Both application versions understand the public "excel" source kind.
SELECT 1;
