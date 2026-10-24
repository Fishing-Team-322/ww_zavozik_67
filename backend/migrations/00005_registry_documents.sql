-- +goose Up
ALTER TABLE product_documents DROP CONSTRAINT product_documents_kind_check;
ALTER TABLE product_documents ADD CONSTRAINT product_documents_kind_check CHECK(kind IN ('invoice','contract','action','signal','import','model_quality','classifier_quality','drift','registry','registry_preview','marketplace_report'));

-- +goose Down
-- Preserve imported documents: rollback must be explicit after exporting new kinds.
ALTER TABLE product_documents DROP CONSTRAINT product_documents_kind_check;
ALTER TABLE product_documents ADD CONSTRAINT product_documents_kind_check CHECK(kind IN ('invoice','contract','action','signal','import','model_quality','classifier_quality','drift')) NOT VALID;
