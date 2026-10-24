ALTER TABLE actual_operations ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 1;
