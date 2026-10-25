-- +goose Up
ALTER TABLE product_documents DROP CONSTRAINT product_documents_kind_check;
ALTER TABLE product_documents ADD CONSTRAINT product_documents_kind_check CHECK(kind IN ('invoice','contract','tax','action','signal','import','model_quality','classifier_quality','drift','registry','registry_preview','marketplace_report'));
CREATE UNIQUE INDEX tax_active_period ON product_documents(company_id,(data->>'kind'),(data->>'year'),(data->>'period')) WHERE kind='tax' AND data->>'status'='active' AND data->>'kind' IN ('usn_advance','usn_annual','vat');

-- +goose Down
-- Keep historical obligations and events; refuse rollback while tax documents exist.
DROP INDEX tax_active_period;
ALTER TABLE product_documents DROP CONSTRAINT product_documents_kind_check;
ALTER TABLE product_documents ADD CONSTRAINT product_documents_kind_check CHECK(kind IN ('invoice','contract','action','signal','import','model_quality','classifier_quality','drift','registry','registry_preview','marketplace_report'));
