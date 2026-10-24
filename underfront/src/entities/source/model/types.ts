export type SourceKind = "upload" | "onec_bank_file" | "excel" | "gsheets" | "onec_odata" | "fns" | "manual";

export interface DataSource {
  id: string;
  kind: SourceKind;
  title: string;
  status: string;
  enabled: boolean;
  last_synced_at: string | null;
  records: number;
  error: string | null;
}

export interface CreateSourceInput {
  kind: SourceKind;
  title?: string;
  config?: Record<string, unknown>;
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  error: string | null;
  result_ref: string | null;
  result: Record<string, unknown> | null;
}

export interface UploadNeedsMapping {
  upload_id: string;
  detected_format: string;
  needs_mapping: true;
}

export interface UploadPreview {
  columns: string[];
  rows: string[][];
  proposed_mapping: Record<string, string>;
}

export interface ImportIssue { row?: number | string; code?: string; message?: string }
export interface ImportReport {
  id: string;
  source_id: string;
  source?: { id: string; kind: string };
  started_at: string;
  added: number;
  duplicates: number;
  duplicate_candidates_retained?: number;
  errors: ImportIssue[];
  status: string;
  period?: { from: string; to: string };
}
