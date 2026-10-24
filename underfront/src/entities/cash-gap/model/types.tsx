export type CashflowSource = "bank" | "invoice" | "contract" | "recurring" | "tax" | "manual";

/** Суммы в рублях; положительное значение — поступление, отрицательное — списание. */
export interface GapCashflowEvent {
  id: string;
  title: string;
  counterparty: string;
  date: string;
  amount: number;
  source: CashflowSource;
  document: string;
  note?: string;
}

export interface GapScenario {
  id: string;
  companyId: string;
  asOf: string;
  startDate: string;
  endDate: string;
  openingBalance: number;
  openingSource: string;
  events: GapCashflowEvent[];
}

export type GapActionEffect =
  | { kind: "move"; eventId: string; date: string }
  | { kind: "split"; eventId: string; parts: Array<{ date: string; amount: number }> }
  | { kind: "add"; events: GapCashflowEvent[] };

export interface GapAction {
  id: string;
  title: string;
  description: string;
  conditions: string;
  effects: GapActionEffect[];
  cost: { amount: number; date: string; counterparty: string } | null;
  conflictsWith: string[];
}

export interface CashGapDetails {
  scenario: GapScenario;
  actions: GapAction[];
  probability: number | null;
  probabilitySource: "mock" | "model";
}

export interface GapDailyBalance {
  date: string;
  opening: number;
  closing: number;
  income: number;
  expense: number;
}

export interface GapForecast {
  days: GapDailyBalance[];
  minimum: number;
  maximumShortfall: number;
  shortfallDays: number;
  firstGapDate: string | null;
  closing: number;
}

export interface WaterfallStep {
  id: string;
  title: string;
  kind: "opening" | "income" | "expense" | "closing";
  amount: number;
  before: number;
  after: number;
  event?: GapCashflowEvent;
}

export interface GapActionPreview {
  actionId: string;
  improvement: number;
  maximumShortfall: number;
  minimum: number;
}

export interface GapSimulation {
  actionIds: string[];
  baseline: GapForecast;
  alternative: GapForecast;
  events: GapCashflowEvent[];
  waterfall: WaterfallStep[];
  actionPreviews: GapActionPreview[];
  totalCost: number;
  alternativeProbability: number | null;
}

export interface SimulateGapRequest { actionIds: string[] }

/** GET gap, POST simulate, POST action/apply. Реальное применение не входит в демо. */
export interface CashGapGateway {
  getGap(companyId: string, gapId: string, signal?: AbortSignal): Promise<CashGapDetails | null>;
  simulate(companyId: string, gapId: string, request: SimulateGapRequest, signal?: AbortSignal): Promise<GapSimulation>;
  applyAction(actionId: string, request: { companyId: string; gapId: string; scenarioId: string }): Promise<{ applied: boolean; operationId: string }>;
}

export type CashGapInspectorStatus = "loading" | "empty" | "ready" | "simulating" | "error";

export interface SavedGapScenario {
  id: string;
  name: string;
  actionIds: string[];
  result: GapSimulation;
}
