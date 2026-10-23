import type { CashflowDay, CashflowRisk } from "@/src/components/finance";
import type { ChartDataPoint, ChartSeriesConfig } from "@/src/components/ui";
import type { Signal } from "@/src/features/cabinet-dashboard/ui";

/** Isolated sample values for /test. They are not forecasts or business records. */
export const chartData: ChartDataPoint[] = [
  { date: "01.11", income: 42, expenses: 31 },
  { date: "02.11", income: 55, expenses: 36 },
  { date: "03.11", income: 48, expenses: 39 },
  { date: "04.11", income: 63, expenses: 42 },
  { date: "05.11", income: 59, expenses: 51 },
  { date: "06.11", income: 72, expenses: 47 },
  { date: "07.11", income: 68, expenses: 53 },
];

export const chartSeries: ChartSeriesConfig[] = [
  { key: "income", name: "Поступления", color: "var(--chart-series-emerald)" },
  { key: "expenses", name: "Расходы", color: "var(--chart-series-amber)" },
];

export const donutData = [
  { name: "Продажи", value: 52 },
  { name: "Услуги", value: 30 },
  { name: "Другое", value: 18 },
];

export type OperationRow = {
  id: string;
  date: string;
  counterparty: string;
  amount: number;
  status: string;
  [key: string]: unknown;
};

export const operations: OperationRow[] = [
  { id: "op-1", date: "23.10.2026", counterparty: "ООО «Маяк»", amount: 84000, status: "Проведено" },
  { id: "op-2", date: "22.10.2026", counterparty: "Аренда офиса", amount: -39000, status: "Проведено" },
  { id: "op-3", date: "21.10.2026", counterparty: "ООО «Север»", amount: 56000, status: "Ожидает" },
  { id: "op-4", date: "20.10.2026", counterparty: "Поставщик", amount: -22000, status: "Проведено" },
];

export const cashflowDays: CashflowDay[] = [
  { date: "01.11", actual: 80000, baseline: 80000, scenario: 80000, events: ["Тестовое начальное значение"] },
  { date: "02.11", actual: 72000, baseline: 72000, scenario: 72000 },
  { date: "03.11", actual: 91000, baseline: 91000, scenario: 91000, events: ["Тестовое поступление"] },
  { date: "04.11", baseline: 65000, scenario: 48000, lowerBound: 53000, upperBound: 77000 },
  { date: "05.11", baseline: 39000, scenario: 12000, lowerBound: 27000, upperBound: 51000, events: ["Тестовый платёж поставщику"] },
  { date: "06.11", baseline: 46000, scenario: -5000, lowerBound: 34000, upperBound: 58000, events: ["Тестовый период дефицита"] },
  { date: "07.11", baseline: 28000, scenario: -30000, lowerBound: 16000, upperBound: 40000, events: ["Тестовый обязательный платёж"] },
];

export const mockRisk: CashflowRisk = {
  id: "test-risk",
  date: "07.11",
  deficit: 30000,
  probability: 0.42,
  reasons: ["Тестовый обязательный платёж", "Поступление сдвинуто в сценарии"],
  recommendation: "Это пример оформления рекомендации, а не финансовый совет.",
};

export const mockSignals: Signal[] = [
  { id: "info", level: "info", title: "Информация", detail: "Пример нейтрального сообщения.", basis: "Тестовое правило" },
  { id: "warning", level: "warning", title: "Внимание", detail: "Пример предупреждения.", basis: "Тестовое правило" },
  { id: "critical", level: "critical", title: "Критично", detail: "Пример срочного сигнала.", basis: "Тестовое правило" },
];
