import type { Forecast } from "@/src/shared/api";

export type ControlCompany = { key: string; name: string; industry: string; legalForm: "ООО" | "ИП"; rows?: number; from?: string; to?: string };
export type ControlSource = { file: File; kind: "csv"; companies: ControlCompany[] };
export type ControlOperation = { id: string; company: string; date: string; amount: number; direction: "in" | "out"; counterparty: string; inn: string; purpose: string; balance: number | null };
export type ControlData = { company: ControlCompany; operations: ControlOperation[]; duplicates: number; from: string; to: string };
export type ActualDay = { date: string; balance: number | null; observed: boolean; reason?: string };
export type CheckpointPoint = { date: string; predicted: number; actual: number | null; lower: number; upper: number; observed: boolean };
export type CheckpointMetrics = {
  samples: number; excluded: number; mae: number | null; mse: number | null; rmse: number | null; wape: number | null; coverage: number | null;
  accuracy: number | null; precision: number | null; recall: number | null; f1: number | null;
  confusion: { tp: number; fp: number; fn: number; tn: number } | null;
  classificationBasis: "median_balance_below_reserve"; points: CheckpointPoint[];
};
export type CheckpointLog = { at: string; event: string; message: string; elapsed_ms?: number; details?: Record<string, unknown> };
export type CheckpointReport = {
  version: 1; id: string; created_at: string; company_id: string; company_name: string; dataset_company: string;
  mode: "holdout" | "forecast"; horizon: number; reserve: number; cutoff: string;
  input: { filename: string; file_sha256: string; training_sha256: string; withheld_sha256: string; training_rows: number; withheld_rows: number; duplicates: number; from: string; to: string };
  forecast: Forecast; metrics: CheckpointMetrics; logs: CheckpointLog[];
  classification: { total: number; by_method: Record<string, number>; reason: string };
  persistence_warning?: string;
};
