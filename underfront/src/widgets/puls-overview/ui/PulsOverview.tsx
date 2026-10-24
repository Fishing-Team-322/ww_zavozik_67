"use client";

/**
 * ПУЛЬС / Runway-inspired overview — pure TSX + Tailwind CSS.
 *
 * USAGE:  import { PulsOverview } from "@/src/widgets/puls-overview";
 *         <PulsOverview />             // synthetic, visibly marked example
 *         <PulsOverview data={null} /> // empty state until data is loaded
 *         <PulsOverview data={apiData} onAddSource={() => ...} />
 *
 * Rendered by the home page inside the persistent CabinetShell, below Breadcrumbs.
 * No CSS modules or extra stylesheet required.
 * All fictional data are labelled. Risk probability is never invented.
 */

import Link from "next/link";
import type { Schemas } from "@/src/shared/api";
import { alertLink } from "@/src/features/notifications";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui/table";
import { Select } from "@/src/shared/ui/select";
import { useId, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  ChevronRight,
  CircleHelp,
  Clock3,
  Plus,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/src/shared/ui/button";
import { Tabs } from "@/src/shared/ui/tabs";

export type ScenarioKey = "base" | "delay" | "downturn";
export type EventCategory = "revenue" | "payroll" | "suppliers" | "taxes" | "other";

export type ForecastDay = {
  date: string; // YYYY-MM-DD, consecutive forecast dates
  base: number; // projected EOD balance, RUB
  delay?: number; // balance after shifting a client payment
  downturn?: number; // balance after revenue downturn
  actual?: number | null;
  p10?: number;
  p50?: number;
  p90?: number;
};

export type HistoryDay = { date: string; actual: number | null };
export type OverdueReceipt = { title: string; counterparty: string; amount: number; dueDate: string };

export type CashEvent = {
  id: string;
  title: string;
  day: number; // days from the start of forecast
  duration?: number; // display-only bar width; not a transaction duration
  category: EventCategory;
  amount: number; // income positive, costs negative
  counterparty?: string;
  source?: string;
  paymentDiscipline?: string; // supplied client history, shown for receipts
};

export type PulsOverviewData = {
  company?: string;
  currentBalance: number;
  safeToSpend?: number | null;
  minimumBalance?: { date: string; p50: number } | null;
  serverStatus?: string;
  headline?: string;
  horizon?: 30 | 60 | 90;
  forecast: ForecastDay[];
  history?: HistoryDay[];
  events: CashEvent[];
  reserve?: number;
  overdueReceipts?: OverdueReceipt[];
  unusualExpenseIds?: string[];
  shortfallProbability?: number | null; // Only supply statistically supported 0..1
  updatedAt?: string;
  isDemo?: boolean;
};

export type PulsOverviewProps = {
  data?: PulsOverviewData | null;
  onAddSource?: () => void;
  horizon?: 30 | 60 | 90;
  onChangeHorizon?: (horizon: 30 | 60 | 90) => void;
  onOpenForecast?: () => void;
  onOpenCalendar?: () => void;
  onOpenEvent?: (id: string) => void;
  onOpenScenarios?: () => void;
  onOpenGap?: () => void;
  onOpenDay?: (date: string) => void;
  alerts?: Schemas["Alert"][];
};

const SCENARIOS: ReadonlyArray<{ key: ScenarioKey; label: string; full: string }> = [
  { key: "base", label: "Базовый", full: "Базовый прогноз" },
  { key: "delay", label: "Оплата +14 дней", full: "Задержка оплаты клиента" },
  { key: "downturn", label: "Выручка −20%", full: "Снижение выручки" },
];

const CATEGORY_ROWS: ReadonlyArray<{ key: EventCategory; label: string }> = [
  { key: "revenue", label: "Поступления клиентов" },
  { key: "payroll", label: "Заработная плата" },
  { key: "suppliers", label: "Аренда и поставщики" },
  { key: "taxes", label: "Налоги и взносы" },
  { key: "other", label: "Операционные расходы" },
];

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
export const formatMoney = (value: number) =>
  `${value < 0 ? "−" : ""}${numberFormat.format(Math.abs(value))} ₽`;

const compactMoney = (value: number) => {
  const sign = value < 0 ? "−" : "";
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) {
    return `${sign}${(magnitude / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} млн ₽`;
  }
  if (magnitude >= 1_000) return `${sign}${Math.round(magnitude / 1_000).toLocaleString("ru-RU")} тыс ₽`;
  return formatMoney(value);
};

const displayDate = (value: string) => {
  const date = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "UTC", day: "numeric", month: "short",
  }).format(date);
};

function scenarioSupported(data: PulsOverviewData, key: ScenarioKey) {
  return key === "base" || (data.forecast.length > 0 && data.forecast.every(p => typeof p[key] === "number" && Number.isFinite(p[key])));
}

export function getForecastStats(points: ForecastDay[], key: ScenarioKey) {
  if (points.length === 0) return { last: 0, minimum: 0, firstNegative: -1, negativeDays: 0, deficit: 0 };
  const balances = points.map(point => point[key] ?? point.base);
  const minimum = Math.min(...balances);
  return {
    last: balances[balances.length - 1],
    minimum,
    firstNegative: balances.findIndex(balance => balance < 0),
    negativeDays: balances.filter(balance => balance < 0).length,
    deficit: Math.max(0, -minimum),
  };
}

// Deterministic sample only. Do not show these figures as your backend's actual prediction.
function createDemo(): PulsOverviewData {
  const events: CashEvent[] = [
    { id: "e1", title: "Оплата по счёту", counterparty: "ООО «Вектор»", day: 7, duration: 5, category: "revenue", amount: 180000, source: "Выставленный счёт", paymentDiscipline: "Обычно оплачивает вовремя" },
    { id: "e2", title: "Оплата этапа работ", counterparty: "ООО «Сфера»", day: 13, duration: 5, category: "revenue", amount: 240000, source: "Договор", paymentDiscipline: "Средняя задержка — 3 дня" },
    { id: "e3", title: "Финальный расчёт", counterparty: "ООО «Маяк»", day: 22, duration: 5, category: "revenue", amount: 390000, source: "Выставленный счёт", paymentDiscipline: "Истории оплат пока нет" },
    { id: "e4", title: "Зарплата", counterparty: "Команда", day: 15, duration: 5, category: "payroll", amount: -600000, source: "Зарплатный проект" },
    { id: "e5", title: "Аренда офиса", counterparty: "БЦ «Каскад»", day: 3, duration: 5, category: "suppliers", amount: -100000, source: "Регулярный платёж" },
    { id: "e6", title: "Поставка материалов", counterparty: "ТехноСнаб", day: 9, duration: 5, category: "suppliers", amount: -135000, source: "Счёт поставщика" },
    { id: "e7", title: "Налоги", counterparty: "ФНС", day: 18, duration: 4, category: "taxes", amount: -120000, source: "Налоговый календарь" },
    { id: "e8", title: "Оборудование", counterparty: "ТехноСнаб", day: 26, duration: 4, category: "other", amount: -145000, source: "Ручное событие" },
  ];
  let base = 470000;
  let delay = 470000;
  let downturn = 470000;
  const forecast: ForecastDay[] = [];
  const reference = new Date("2026-10-24T00:00:00Z");
  const history: HistoryDay[] = [];
  for (let offset = -14; offset < 0; offset += 1) {
    const date = new Date(reference);
    date.setUTCDate(date.getUTCDate() + offset);
    history.push({ date: date.toISOString().slice(0, 10), actual: 470000 + offset * 3400 + (offset % 4) * 4200 });
  }
  for (let day = 0; day <= 90; day += 1) {
    if (day > 0) {
      const dailyIncome = 18000 + (day % 5) * 2400;
      const dailyExpense = 15500 + (day % 4) * 3100;
      const todays = events.filter(event => event.day === day);
      const receipts = todays.filter(event => event.amount > 0).reduce((acc, event) => acc + event.amount, 0);
      const costs = todays.filter(event => event.amount < 0).reduce((acc, event) => acc + event.amount, 0);
      base += dailyIncome - dailyExpense + receipts + costs;
      delay += dailyIncome - dailyExpense + receipts + costs
        - (day === 13 ? 240000 : 0) + (day === 27 ? 240000 : 0);
      downturn += dailyIncome * 0.8 - dailyExpense + receipts * 0.8 + costs;
    }
    const d = new Date(reference);
    d.setUTCDate(d.getUTCDate() + day);
    const spread = day * 3400;
    forecast.push({ date: d.toISOString().slice(0, 10), base: Math.round(base), delay: Math.round(delay), downturn: Math.round(downturn), actual: day === 0 ? 470000 : null, p10: Math.round(base - spread), p50: Math.round(base), p90: Math.round(base + spread * 0.85) });
  }
  return { currentBalance: 470000, company: "ООО «Горизонт»", forecast, history, events, reserve: 100000, shortfallProbability: 0.64, overdueReceipts: [{ title: "Просроченная оплата", counterparty: "ООО «Орион»", amount: 110000, dueDate: "2026-10-21" }], unusualExpenseIds: ["e8"], isDemo: true };
}
export const PULS_DEMO_DATA = createDemo();

/** Small SVG, no charting dependencies or extra CSS. */
export function KpiSparkline({
  first, second, id,
}: { first: number[]; second?: number[]; id: string }) {
  const width = 250;
  const height = 84;
  const values = first.concat(second ?? []);
  const min = Math.min(...values);
  const spread = Math.max(1, Math.max(...values) - min);
  const mapPoints = (series: number[]) => series.map((point, idx) =>
    `${(idx / Math.max(1, series.length - 1)) * width},${height - 7 - ((point - min) / spread) * (height - 18)}`,
  ).join(" L");
  const firstPath = `M${mapPoints(first)}`;
  const secondPath = second ? `M${mapPoints(second)}` : "";
  return <svg className="block h-[88px] w-full flex-1" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
    <defs>
      <linearGradient id={`mint-${id}`} x1="0" y1="0" x2="0" y2="1">
        <stop stopColor="var(--puls-chart-primary)" stopOpacity=".19"/><stop offset="1" stopColor="var(--puls-chart-primary)" stopOpacity="0"/>
      </linearGradient>
      <linearGradient id={`violet-${id}`} x1="0" y1="0" x2="0" y2="1">
        <stop stopColor="var(--puls-chart-secondary)" stopOpacity=".14"/><stop offset="1" stopColor="var(--puls-chart-secondary)" stopOpacity="0"/>
      </linearGradient>
    </defs>
    <path d={`${firstPath} L${width},${height} L0,${height}Z`} fill={`url(#mint-${id})`}/>
    {second && <path d={`${secondPath} L${width},${height} L0,${height}Z`} fill={`url(#violet-${id})`}/>}
    <path d={firstPath} stroke="var(--puls-chart-primary)" strokeWidth="1.7" fill="none" vectorEffect="non-scaling-stroke"/>
    {second && <path d={secondPath} stroke="var(--puls-chart-secondary)" strokeWidth="1.5" fill="none" vectorEffect="non-scaling-stroke"/>}
    <line x1="69%" x2="69%" y1="0" y2={height} stroke="var(--puls-border-strong)" strokeWidth="1"/>
  </svg>;
}

export function KpiStrip({ data, selected }: { data: PulsOverviewData; selected: ScenarioKey }) {
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(period, selected);
  const minimum = selected === "base" && data.minimumBalance ? data.minimumBalance.p50 : stats.minimum;
  const minimumDay = selected === "base" && data.minimumBalance ? data.minimumBalance : period.find(p => (p[selected] ?? p.base) === minimum);
  const spendable = data.isDemo ? Math.max(0, Math.min(data.currentBalance, stats.minimum - (data.reserve ?? 0))) : data.safeToSpend;
  const change = stats.last - data.currentBalance;
  const reserveGap = minimum - (data.reserve ?? 0);
  const items = [
    { title: "Текущий баланс", value: compactMoney(data.currentBalance), detail: `Резерв: ${compactMoney(data.reserve ?? 0)}`, hint: "На счетах сегодня" },
    { title: "Можно потратить сегодня", value: spendable == null ? "Нет оценки" : compactMoney(spendable), detail: "С учётом резерва и неопределённости", hint: data.isDemo ? "Демонстрационная оценка" : "По расчёту сервиса" },
    { title: "Минимальный остаток", value: compactMoney(minimum), detail: reserveGap < 0 ? `Ниже резерва на ${compactMoney(-reserveGap)}` : `Выше резерва на ${compactMoney(reserveGap)}`, hint: minimumDay ? `${displayDate(minimumDay.date)} · по выбранному сценарию` : "Нижняя точка за выбранный период" },
    { title: `Остаток через ${data.horizon ?? 30} дней`, value: compactMoney(stats.last), detail: `${change > 0 ? "+" : ""}${compactMoney(change)} к сегодняшнему дню`, hint: "По выбранному сценарию" },
  ];
  return <section aria-label="Ключевые показатели" className="grid grid-cols-2 border border-[color:var(--puls-border)] bg-[color:var(--puls-bg)] xl:grid-cols-4">
    {items.map((item, index) => <div key={item.title} className={`flex min-h-[126px] min-w-0 flex-col border-[color:var(--puls-border)] p-3.5 xl:border-r xl:border-b-0 xl:last:border-r-0 ${index < 2 ? "border-b" : ""} ${index % 2 === 0 ? "border-r" : ""}`}>
      <p className="text-[12px] font-medium leading-4 text-[color:var(--puls-text-secondary)] sm:text-[13px]">{item.title}</p>
      <strong className="mt-3 text-[18px] font-semibold leading-6 tracking-[-0.025em] tabular-nums text-[color:var(--puls-text-strong)] sm:text-[20px]">{item.value}</strong>
      <div className="mt-auto border-t border-[color:var(--puls-border)] pt-2">
        <p className="text-[12px] font-medium leading-4 text-[color:var(--puls-text)]">{item.detail}</p>
        <p className="mt-0.5 text-[11px] leading-4 text-[color:var(--puls-text-muted)]">{item.hint}</p>
      </div>
    </div>)}
  </section>;
}

function FinancialStatus({ data, onOpenGap }: { data: PulsOverviewData; onOpenGap?: () => void }) {
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(period, "base");
  const firstGap = stats.firstNegative >= 0 ? period[stats.firstNegative] : null;
  const probability = data.shortfallProbability;
  const riskPercent = probability == null ? null : Math.round(probability * 1000) / 10;
  const severity = data.serverStatus ? (({ ok: "Спокойно", warning: "Внимание", danger: "Опасно" } as Record<string, string>)[data.serverStatus] ?? "Нет оценки") : probability == null
    ? stats.deficit > 0 ? "Опасно" : "Спокойно"
    : probability > 0.4 ? "Опасно" : probability >= 0.1 ? "Внимание" : "Спокойно";
  const accent = severity === "Спокойно" ? "text-[color:var(--puls-good-text)]" : severity === "Внимание" ? "text-[color:var(--puls-demo-text)]" : "text-[color:var(--puls-chart-zero)]";
  return <section aria-label="Финансовое состояние" className="mb-5 flex flex-col gap-3 border-y border-[color:var(--puls-border)] bg-[color:var(--puls-surface-soft)] px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
    <div className="flex min-w-0 items-start gap-3">
      <AlertTriangle size={16} className={`mt-1 shrink-0 ${accent}`} aria-hidden="true"/>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><h2 className={`text-[16px] font-semibold leading-5 ${accent}`}>{severity}</h2><span className="text-[12px] text-[color:var(--puls-text-secondary)]">{riskPercent == null ? "Вероятность разрыва: нет оценки" : `Вероятность разрыва: ${riskPercent}%${data.isDemo ? " · демо-оценка" : ""}`}</span></div>
        <p className="mt-1 text-[13px] leading-5 text-[color:var(--puls-text-secondary)]">{data.headline ?? (firstGap ? `По базовому прогнозу с ${displayDate(firstGap.date)} возможна нехватка; максимальный дефицит — ${formatMoney(stats.deficit)}.` : "Базовый прогнозный остаток остаётся положительным в выбранном периоде.")}</p>
      </div>
    </div>
    {onOpenGap && <Button type="button" variant="outline" size="md" onClick={onOpenGap} className="w-fit shrink-0">Что делать <ChevronRight aria-hidden="true"/></Button>}
  </section>;
}

type OverviewChartPoint = ForecastDay & { selectedValue?: number | null; corridor?: [number, number]; historical?: boolean };

function ForecastTooltip({ active, label, rows, selected, events, reserve }: {
  active?: boolean;
  label?: string | number;
  rows: OverviewChartPoint[];
  selected: ScenarioKey;
  events: CashEvent[];
  reserve?: number;
}) {
  if (!active) return null;
  const day = rows.find(row => row.date === label);
  if (!day) return null;
  const payments = day.historical ? [] : events.filter(event => event.day >= 0 && rowDateForEvent(event, rows) === day.date);
  const currentScenario = SCENARIOS.find(s => s.key === selected)!;
  return <div className="min-w-[210px] max-w-[290px] rounded-[5px] border border-[color:var(--puls-border)] bg-[color:var(--puls-bg)] p-3 text-[11px] text-[color:var(--puls-text-secondary)] shadow-none">
    <strong className="mb-2 block text-[12px] text-[color:var(--puls-text)]">{displayDate(day.date)}</strong>
    {day.actual != null && <p className="flex justify-between gap-3"><span>Факт</span><b className="tabular-nums text-[color:var(--puls-text-strong)]">{formatMoney(day.actual)}</b></p>}
    {!day.historical && <>
      <p className="mt-1 flex justify-between gap-3"><span>Базовый / p50</span><b className="tabular-nums text-[color:var(--puls-text-strong)]">{formatMoney(day.p50 ?? day.base)}</b></p>
      {day.p10 != null && day.p90 != null && <p className="mt-1 flex justify-between gap-3"><span>Коридор p10–p90</span><b className="tabular-nums text-[color:var(--puls-text-strong)]">{compactMoney(day.p10)} — {compactMoney(day.p90)}</b></p>}
      {selected !== "base" && <p className="mt-1 flex justify-between gap-3"><span>{currentScenario.label}</span><b className="tabular-nums text-[color:var(--puls-text-strong)]">{formatMoney(day[selected] ?? day.base)}</b></p>}
      {reserve != null && <p className="mt-1 flex justify-between gap-3"><span>Резерв</span><b className="tabular-nums text-[color:var(--puls-text-strong)]">{formatMoney(reserve)}</b></p>}
      {payments.length > 0 && <div className="mt-2 space-y-1 border-t border-[color:var(--puls-border)] pt-2">{payments.map(event => <p key={event.id} className="flex justify-between gap-2"><span className="min-w-0 truncate">{event.title} · {event.counterparty ?? "—"}</span><b className="shrink-0 tabular-nums">{event.amount > 0 ? "+" : ""}{compactMoney(event.amount)}</b></p>)}</div>}
    </>}
  </div>;
}

function rowDateForEvent(event: CashEvent, rows: OverviewChartPoint[]) {
  const firstForecast = rows.findIndex(row => !row.historical);
  return rows[firstForecast + event.day]?.date;
}

export function ForecastChart({ data, selected, horizon, onChangeHorizon, onChangeScenario, onOpenForecast, onOpenDay }: {
  data: PulsOverviewData;
  selected: ScenarioKey;
  horizon: 30 | 60 | 90;
  onChangeHorizon: (value: 30 | 60 | 90) => void;
  onChangeScenario: (key: ScenarioKey) => void;
  onOpenForecast?: () => void;
  onOpenDay?: (date: string) => void;
}) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const visible = data.forecast.slice(0, horizon + 1);
  const risk = getForecastStats(visible, selected);
  const currentScenario = SCENARIOS.find(s => s.key === selected)!;
  const chartPoints: OverviewChartPoint[] = [
    ...(data.history ?? []).map(point => ({ date: point.date, base: 0, actual: point.actual, historical: true, selectedValue: null })),
    ...visible.map(point => ({ ...point, p50: point.p50 ?? point.base, selectedValue: point[selected] ?? point.base, corridor: point.p10 != null && point.p90 != null ? [point.p10, point.p90] as [number, number] : undefined })),
  ];
  const ticks = chartPoints.filter((_, index) => index === 0 || index === chartPoints.length - 1 || index % Math.max(6, Math.round(chartPoints.length / 6)) === 0).map(p => p.date);
  const eventPoints = data.events.filter(event => event.day >= 0 && event.day <= horizon && visible[event.day]);
  return <section aria-label="Прогноз денежных средств" className="mt-9 min-w-0">
    <header className="mb-4 flex flex-wrap items-start justify-between gap-x-5 gap-y-3">
      <div><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Финансовый прогноз <span className="font-normal text-[color:var(--puls-text-faint)]">/ {horizon} дней</span></h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">История, {data.isDemo ? "демо-коридор" : "прогнозный коридор"} и сравнение сценариев</p></div>
      <div className="flex max-w-full flex-wrap items-center gap-2">
        <Tabs ariaLabel="Период прогноза" size="sm" tabs={([30, 60, 90] as const).map(value => ({ key: String(value), label: `${value} дн.`, content: null }))} value={String(horizon)} onValueChange={(value) => onChangeHorizon(Number(value) as 30 | 60 | 90)} showContent={false}/>
        <Tabs
          ariaLabel="Выберите сценарий"
          size="sm"
          tabs={SCENARIOS.map((scenario) => ({
            key: scenario.key,
            label: scenario.label,
            content: null,
            disabled: !scenarioSupported(data, scenario.key),
          }))}
          value={selected}
          onValueChange={(value) => onChangeScenario(value as ScenarioKey)}
          showContent={false}
        />
        {onOpenForecast && <Button type="button" variant="outline" size="icon" aria-label="Открыть полный прогноз" onClick={onOpenForecast} className="text-[color:var(--puls-text-secondary)]! hover:text-[color:var(--puls-chart-primary)]!"><ArrowUpRight aria-hidden="true" /></Button>}
      </div>
    </header>
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-[color:var(--puls-text-secondary)]">
      <span className="flex items-center gap-1.5"><span className="h-0.5 w-[20px] bg-[color:var(--puls-text-muted)]"/>Факт</span>
      <span className="flex items-center gap-1.5"><span className="h-0.5 w-[20px] bg-[color:var(--puls-chart-primary)]"/>Прогноз p50</span>
      <span className="flex items-center gap-1.5"><span className="size-2.5 bg-[color:var(--accent-soft)]"/>Коридор p10–p90</span>
      {selected !== "base" && <span className="flex items-center gap-1.5"><span className="h-0.5 w-[20px] bg-[color:var(--puls-chart-secondary)]"/>{currentScenario.full}</span>}
      {data.reserve != null && <span className="flex items-center gap-1.5"><span className="w-[16px] border-t border-dashed border-[color:var(--puls-text-muted)]"/>Резерв</span>}
      <span className="flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-[color:var(--puls-text-strong)]"/>Важный платёж</span>
    </div>
    <div className="h-[265px] w-full min-w-0 border-b border-[color:var(--puls-border)] sm:h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartPoints} margin={{ top: 9, right: 8, bottom: 2, left: 0 }} onClick={state => {
          const date = state?.activeLabel;
          if (typeof date === "string" && visible.some(point => point.date === date)) onOpenDay?.(date);
        }}>
          <defs>
            <linearGradient id={`${reactId}-base`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-primary)" stopOpacity={0.17}/><stop offset="1" stopColor="var(--puls-chart-primary)" stopOpacity={0}/></linearGradient>
            <linearGradient id={`${reactId}-alt`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-secondary)" stopOpacity={0.13}/><stop offset="1" stopColor="var(--puls-chart-secondary)" stopOpacity={0}/></linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--puls-grid)" strokeDasharray="3 5"/>
          <XAxis dataKey="date" ticks={ticks} tickFormatter={displayDate} tickLine={false} axisLine={false} fontSize={11} dy={10} tick={{ fill: "var(--puls-text-muted)" }}/>
          <YAxis width={62} tickLine={false} axisLine={false} fontSize={11} tick={{ fill: "var(--puls-text-muted)" }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}/>
          <Tooltip cursor={{ stroke: "var(--puls-text-muted)", strokeDasharray: "4 4" }} content={({ active, label }) => <ForecastTooltip active={active} label={label} rows={chartPoints} selected={selected} events={data.events} reserve={data.reserve}/>}/>
          <ReferenceLine y={0} stroke="var(--puls-chart-zero)" strokeDasharray="5 5" strokeWidth={1.2}/>
          {data.reserve != null && <ReferenceLine y={data.reserve} stroke="var(--puls-text-muted)" strokeDasharray="3 4" strokeWidth={1}/>}
          {risk.firstNegative >= 0 && <ReferenceLine x={visible[risk.firstNegative].date} stroke="var(--puls-chart-zero)" strokeDasharray="3 5"/>}
          <Area type="linear" dataKey="corridor" fill="var(--accent-soft)" stroke="none" isAnimationActive={false} tooltipType="none"/>
          <Area type="linear" dataKey="p50" fill={`url(#${reactId}-base)`} stroke="none" isAnimationActive={false} tooltipType="none"/>
          {selected !== "base" && <Area type="linear" dataKey="selectedValue" fill={`url(#${reactId}-alt)`} stroke="none" isAnimationActive={false} tooltipType="none"/>}
          <Line type="linear" name="Факт" dataKey="actual" stroke="var(--puls-text-muted)" strokeWidth={1.7} dot={false} isAnimationActive={false}/>
          <Line type="linear" name="p10" dataKey="p10" stroke="var(--puls-chart-primary)" strokeOpacity={0.48} strokeDasharray="2 4" dot={false} isAnimationActive={false}/>
          <Line type="linear" name="p90" dataKey="p90" stroke="var(--puls-chart-primary)" strokeOpacity={0.48} strokeDasharray="2 4" dot={false} isAnimationActive={false}/>
          <Line type="linear" name="Базовый p50" dataKey="p50" stroke="var(--puls-chart-primary)" strokeWidth={2.1} dot={false} activeDot={{ r: 4, fill: "var(--puls-chart-primary)", stroke: "var(--puls-bg)", strokeWidth: 2 }} isAnimationActive={false}/>
          {selected !== "base" && <Line type="linear" name={currentScenario.full} dataKey="selectedValue" stroke="var(--puls-chart-secondary)" strokeWidth={2} strokeDasharray="6 4" dot={false} activeDot={{ r: 4, fill: "var(--puls-chart-secondary)", stroke: "var(--puls-bg)", strokeWidth: 2 }} isAnimationActive={false}/>}
          {eventPoints.map(event => <ReferenceDot key={event.id} x={visible[event.day].date} y={visible[event.day].base} r={3.5} fill={event.amount > 0 ? "var(--puls-chart-primary)" : "var(--puls-text-strong)"} stroke="var(--puls-bg)" strokeWidth={1} ifOverflow="visible"/>)}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    {onOpenDay && <Select label="Подробности дня" containerClassName="mt-3 max-w-xs" value="" options={[{ value: "", label: "Выберите день на графике или в списке" }, ...visible.map(point => ({ value: point.date, label: displayDate(point.date) }))]} onChange={event => { if (event.target.value) onOpenDay(event.target.value); }} />}
  </section>;
}

function NearTermFlows({ data, onOpenCalendar, onOpenEvent }: { data: PulsOverviewData; onOpenCalendar?: () => void; onOpenEvent?: (id: string) => void }) {
  const events = data.events.filter(event => event.day >= 0 && event.day <= 14 && data.forecast[event.day]).sort((a, b) => a.day - b.day);
  const groups = [
    { title: "Ближайшие платежи", items: events.filter(event => event.amount < 0), color: "text-[color:var(--puls-text-strong)]" },
    { title: "Ожидаемые поступления", items: events.filter(event => event.amount > 0), color: "text-[color:var(--puls-positive-text)]" },
  ];
  return <div className="mt-7 grid min-w-0 gap-5 lg:grid-cols-2 lg:gap-7">
    {groups.map(group => <section key={group.title} className="min-w-0 border-t border-[color:var(--puls-border)]">
      <header className="flex items-center justify-between gap-3 py-3"><div><h2 className="text-[16px] font-semibold text-[color:var(--puls-text)]">{group.title}</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">На ближайшие 14 дней</p></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" onClick={onOpenCalendar}>Календарь <ChevronRight aria-hidden="true"/></Button>}</header>
      <div className="border-y border-[color:var(--puls-border)]">{group.items.length ? group.items.map(event => <div key={event.id} className="grid grid-cols-[55px_minmax(0,1fr)_auto] items-center gap-2 border-b border-[color:var(--puls-border)] px-1 py-2.5 text-[13px] last:border-b-0 hover:bg-[color:var(--puls-surface-soft)] sm:gap-3">
        <span className="text-[12px] text-[color:var(--puls-text-muted)]">{displayDate(data.forecast[event.day].date)}</span>
        <span className="min-w-0"><span className="block truncate font-medium text-[color:var(--puls-text)]">{onOpenEvent ? <Button type="button" variant="ghost" className="h-auto! max-w-full truncate rounded-none! border-0! p-0! text-left text-[13px]! text-inherit! underline underline-offset-2 hover:bg-transparent! hover:text-inherit!" onClick={() => onOpenEvent(event.id)}>{event.title}</Button> : event.title}</span><span className="block truncate text-[12px] text-[color:var(--puls-text-secondary)]">{event.counterparty ?? "Контрагент не указан"}</span><span className="block truncate text-[11px] text-[color:var(--puls-text-muted)]" title={event.amount < 0 ? event.source ?? "Источник не указан" : event.paymentDiscipline ?? "Истории оплат пока нет"}>{event.amount < 0 ? `Источник: ${event.source ?? "не указан"}` : `Дисциплина: ${event.paymentDiscipline ?? "истории оплат нет"}`}</span></span>
        <strong className={`whitespace-nowrap text-right font-medium tabular-nums ${group.color}`}>{event.amount > 0 ? "+" : ""}{formatMoney(event.amount)}</strong>
      </div>) : <p className="px-1 py-4 text-[12px] text-[color:var(--puls-text-secondary)]">Событий на ближайшие 14 дней нет.</p>}</div>
    </section>)}
  </div>;
}

function OverviewAlerts({ alerts }: { alerts: Schemas["Alert"][] }) {
  if (!alerts.length) return null;
  return <section aria-label="Предупреждения" className="mt-9 min-w-0">
    <header className="mb-3"><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Предупреждения</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">События, которые стоит проверить</p></header>
    <div className="border-y border-[color:var(--puls-border)]">{alerts.map(alert => <div key={alert.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color:var(--puls-border)] px-1 py-3 last:border-b-0">
      <AlertTriangle size={16} aria-label={alert.severity === "danger" ? "Опасно" : alert.severity === "warning" ? "Внимание" : "Информация"} className={`shrink-0 ${alert.severity === "danger" ? "text-[color:var(--puls-chart-zero)]" : alert.severity === "warning" ? "text-[color:var(--puls-demo-text)]" : "text-[color:var(--puls-text-secondary)]"}`} />
      <div className="min-w-[180px] flex-1 text-[13px]"><strong className="font-medium text-[color:var(--puls-text)]">{alert.title}</strong>{!alert.read && <span className="ml-2 text-[11px] text-[color:var(--puls-text-muted)]">Новое</span>}<p className="mt-0.5 text-[12px] text-[color:var(--puls-text-secondary)]">{alert.body}</p></div>
      <Link href={alertLink(alert.ref)} className="inline-flex items-center gap-1 text-[12px] text-[color:var(--puls-text-secondary)] underline underline-offset-2">Подробнее <ChevronRight size={12} aria-hidden="true" /></Link>
    </div>)}</div>
  </section>;
}

function DemoWarnings({ data, selected, onOpenGap, onOpenCalendar }: { data: PulsOverviewData; selected: ScenarioKey; onOpenGap?: () => void; onOpenCalendar?: () => void }) {
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(period, selected);
  const firstGap = stats.firstNegative >= 0 ? period[stats.firstNegative] : null;
  const unusual = data.events.filter(event => data.unusualExpenseIds?.includes(event.id) && event.amount < 0);
  const overdue = data.overdueReceipts ?? [];
  if (!firstGap && overdue.length === 0 && unusual.length === 0) return null;
  return <section aria-label="Предупреждения" className="mt-9 min-w-0">
    <header className="mb-3"><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Предупреждения</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">События, которые стоит проверить</p></header>
    <div className="border-y border-[color:var(--puls-border)]">
      {firstGap && <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color:var(--puls-border)] px-1 py-3 last:border-b-0"><AlertTriangle size={16} className="shrink-0 text-[color:var(--puls-chart-zero)]"/><div className="min-w-[180px] flex-1 text-[13px]"><strong className="font-medium text-[color:var(--puls-text)]">Возможная нехватка денег · {displayDate(firstGap.date)}</strong><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-secondary)]">Максимальный дефицит по выбранному сценарию: {formatMoney(stats.deficit)}</p></div>{onOpenGap && <Button type="button" variant="ghost" size="sm" onClick={onOpenGap}>Подробнее <ChevronRight aria-hidden="true"/></Button>}</div>}
      {overdue.map(item => <div key={`${item.dueDate}-${item.counterparty}`} className="flex items-start gap-3 border-b border-[color:var(--puls-border)] px-1 py-3 last:border-b-0"><Clock3 size={16} className="mt-0.5 shrink-0 text-[color:var(--puls-demo-text)]"/><div className="min-w-0 text-[13px]"><strong className="font-medium text-[color:var(--puls-text)]">Просроченное поступление · {item.counterparty}</strong><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-secondary)]">{item.title}: {formatMoney(item.amount)}, срок {displayDate(item.dueDate)}. Не включено в прогноз.</p></div></div>)}
      {unusual.map(event => <div key={event.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-[color:var(--puls-border)] px-1 py-3 last:border-b-0"><Activity size={16} className="shrink-0 text-[color:var(--puls-demo-text)]"/><div className="min-w-[180px] flex-1 text-[13px]"><strong className="font-medium text-[color:var(--puls-text)]">Необычное списание · {event.title}</strong><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-secondary)]">{event.counterparty ?? "Контрагент не указан"} · {data.forecast[event.day] ? displayDate(data.forecast[event.day].date) : `День ${event.day}`} · {formatMoney(event.amount)}{data.isDemo ? " · демо-метка" : ""}</p></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" onClick={onOpenCalendar}>Календарь <ChevronRight aria-hidden="true"/></Button>}</div>)}
    </div>
  </section>;
}

function OverviewPreviews({ data, selected, onChangeScenario, onOpenCalendar, onOpenScenarios }: {
  data: PulsOverviewData;
  selected: ScenarioKey;
  onChangeScenario: (key: ScenarioKey) => void;
  onOpenCalendar?: () => void;
  onOpenScenarios?: () => void;
}) {
  const near = data.events.filter(event => event.day >= 0 && event.day <= 14);
  const incoming = near.reduce((total, event) => total + Math.max(0, event.amount), 0);
  const outgoing = near.reduce((total, event) => total + Math.max(0, -event.amount), 0);
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  return <div className="mt-9 grid min-w-0 gap-5 lg:grid-cols-2 lg:gap-7">
    <section aria-label="Превью платёжного календаря" className="min-w-0 border-t border-[color:var(--puls-border)]">
      <header className="flex items-center justify-between gap-3 py-3"><div><h2 className="text-[16px] font-semibold text-[color:var(--puls-text)]">Платёжный календарь</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">План на ближайшие 14 дней</p></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" onClick={onOpenCalendar}>Открыть <ChevronRight aria-hidden="true"/></Button>}</header>
      <div className="grid grid-cols-3 gap-2 border-t border-[color:var(--puls-border)] py-3 text-[12px]"><div><span className="block text-[color:var(--puls-text-muted)]">Событий</span><strong className="mt-1 block text-[15px] font-semibold tabular-nums text-[color:var(--puls-text)]">{near.length}</strong></div><div><span className="block text-[color:var(--puls-text-muted)]">Поступления</span><strong className="mt-1 block text-[15px] font-semibold tabular-nums text-[color:var(--puls-positive-text)]">{compactMoney(incoming)}</strong></div><div><span className="block text-[color:var(--puls-text-muted)]">Списания</span><strong className="mt-1 block text-[15px] font-semibold tabular-nums text-[color:var(--puls-text)]">{compactMoney(outgoing)}</strong></div></div>
    </section>
    <section aria-label="Превью сравнения сценариев" className="min-w-0 border-t border-[color:var(--puls-border)]">
      <header className="flex items-center justify-between gap-3 py-3"><div><h2 className="text-[16px] font-semibold text-[color:var(--puls-text)]">Сценарии</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">Остаток в конце периода</p></div>{onOpenScenarios && <Button type="button" variant="ghost" size="sm" onClick={onOpenScenarios}>Сравнить <ChevronRight aria-hidden="true"/></Button>}</header>
      <div className="divide-y divide-[color:var(--puls-border)] border-t border-[color:var(--puls-border)]">{SCENARIOS.filter(scenario => scenarioSupported(data, scenario.key)).map(scenario => {
        const stats = getForecastStats(period, scenario.key);
        return <Button variant="ghost" key={scenario.key} type="button" aria-pressed={selected === scenario.key} onClick={() => onChangeScenario(scenario.key)} className={`h-auto! rounded-none! border-0! flex w-full items-center justify-between! gap-3! px-1! py-1.5! font-normal! text-left text-[12px] transition-colors hover:bg-[color:var(--puls-surface-soft)] focus-visible:outline-2 focus-visible:outline-[color:var(--puls-chart-primary)] ${selected === scenario.key ? "bg-[color:var(--puls-surface-muted)] text-[color:var(--puls-text)]" : "text-[color:var(--puls-text-secondary)]"}`}><span className="min-w-0 truncate">{scenario.label}</span><strong className="shrink-0 font-medium tabular-nums text-[color:var(--puls-text-strong)]">{compactMoney(stats.last)}</strong></Button>;
      })}</div>
    </section>
  </div>;
}

export function PaymentTimeline({ data, onOpenCalendar }: { data: PulsOverviewData; onOpenCalendar?: () => void }) {
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const current = data.events.find(e => e.id === selectedEvent);
  const segments = Array.from({ length: 5 }, (_, i) => displayDate(data.forecast[Math.min(i * 6, data.forecast.length - 1)]?.date ?? ""));
  return <section aria-label="Календарь платежей" className="mt-10 min-w-0">
    <header className="mb-4 flex items-start justify-between gap-3">
      <div><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Календарь платежей</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">Поступления и обязательные списания на временной шкале</p></div>
      <Button type="button" variant="outline" size="md" onClick={onOpenCalendar} disabled={!onOpenCalendar}><CalendarDays aria-hidden="true"/>30 дней</Button>
    </header>
    <div className="w-full overflow-x-auto border-b border-[color:var(--puls-border)]">
      <div className="min-w-[850px]">
        <div className="grid h-[38px] grid-cols-[235px_minmax(0,1fr)] text-[12px] text-[color:var(--puls-text-muted)]">
          <div className="self-end border-r border-[color:var(--puls-border-strong)] px-2 pb-2">Плановые события</div>
          <div className="grid grid-cols-5 items-end border-b border-[color:var(--puls-border-strong)] text-center">{segments.map((text, index) => <span key={index} className="pb-2">{text}</span>)}</div>
        </div>
        {CATEGORY_ROWS.map(({ key, label }, rowIndex) => <div key={key} className="grid h-[44px] grid-cols-[235px_minmax(0,1fr)]">
          <div className="flex min-w-0 items-center gap-1.5 border-r border-b border-dashed border-[color:var(--puls-border-strong)] px-2 text-[12px] text-[color:var(--puls-text-secondary)] last:border-b-0"><ChevronRight size={14} className="shrink-0 text-[color:var(--puls-text-muted)]"/>{label}</div>
          <div className={`[background-image:repeating-linear-gradient(to_right,transparent_0,transparent_calc(20%_-_1px),var(--puls-grid)_calc(20%_-_1px),var(--puls-grid)_20%)] relative min-w-0 overflow-hidden border-b border-[color:var(--puls-border)] ${rowIndex % 2 === 0 ? "bg-[color:var(--puls-surface-soft)]" : "bg-[color:var(--puls-surface-muted)]"}`}>
            {data.events.filter(event => event.category === key).map(event => {
              const day = Math.max(0, Math.min(30, event.day));
              // Avoid overflowing the grid at the right edge; bars are display-only.
              const widthPercent = Math.max(12, ((event.duration ?? 4) / 30) * 100);
              const leftPercent = Math.min(day / 30 * 100, 100 - widthPercent);
              const isCurrent = event.id === selectedEvent;
              return <Button variant="ghost" key={event.id} type="button" title={`${event.title} · ${formatMoney(event.amount)} · ${event.source ?? "План"}`} aria-pressed={isCurrent} onClick={() => setSelectedEvent(isCurrent ? null : event.id)} style={{ left: `${leftPercent}%`, width: `${widthPercent}%` }} className={`justify-start! py-0! font-normal! hover:bg-[color:var(--puls-bg)]! hover:text-[color:var(--puls-text)]! absolute! top-[7px] z-10 flex h-[30px]! min-w-[104px] max-w-full cursor-pointer items-center gap-1.5 overflow-hidden rounded-[5px] border bg-[color:var(--puls-bg)]! px-1.5 text-left text-[11px]! text-[color:var(--puls-text)]! shadow-[var(--puls-event-shadow)] transition-shadow hover:z-20 hover:shadow-md focus-visible:outline-2 focus-visible:outline-[color:var(--focus-ring-strong)] ${event.amount >= 0 ? "border-[color:var(--puls-border)] border-l-[3px] border-l-[color:var(--puls-chart-primary)]" : "border-[color:var(--puls-border)] border-l-[3px] border-l-[color:var(--puls-negative-text)]"} ${isCurrent ? "ring-2 ring-[color:var(--focus-ring-strong)]" : ""}`}>
                <span className={`flex size-[18px] shrink-0 items-center justify-center rounded-full ${event.amount >= 0 ? "bg-[color:var(--puls-positive-bg)] text-[color:var(--puls-positive-text)]" : "bg-[color:var(--puls-negative-bg)] text-[color:var(--puls-negative-text)]"}`}>{event.amount >= 0 ? <ArrowDownRight size={13}/> : <ArrowUpRight size={13}/>}</span>
                <span className="truncate">{event.title}</span>
              </Button>;
            })}
          </div>
        </div>)}
      </div>
    </div>
    {current ? <div className="mt-3 flex items-center gap-3 rounded-md border border-[color:var(--puls-border)] bg-[color:var(--puls-surface-soft)] px-3 py-2.5">
      <div className="mr-auto min-w-0"><p className="text-[12px] font-semibold text-[color:var(--puls-text)]">{current.title}</p><p className="mt-0.5 text-[11px] text-[color:var(--puls-text-muted)]">{displayDate(data.forecast[Math.max(0, Math.min(current.day, data.forecast.length - 1))].date)} · {current.source ?? "Плановое событие"}</p></div>
      <strong className={`shrink-0 text-[13px] ${current.amount >= 0 ? "text-[color:var(--puls-positive-text)]" : "text-[color:var(--puls-negative-text)]"}`}>{current.amount > 0 ? "+" : ""}{formatMoney(current.amount)}</strong>
      <Button type="button" variant="ghost" size="icon" aria-label="Закрыть детали" onClick={() => setSelectedEvent(null)} className="shrink-0 cursor-pointer text-[color:var(--puls-text-muted)]! hover:bg-transparent! hover:text-[color:var(--puls-text)]!"><X size={17} className="size-[17px]!"/></Button>
    </div> : <p className="mt-2.5 text-[11px] text-[color:var(--puls-text-faint)]">Нажми на событие, чтобы посмотреть сумму, дату и источник данных.</p>}
  </section>;
}

export function ScenarioComparison({ data, selected, onChangeScenario, onOpenScenarios }: {
  data: PulsOverviewData; selected: ScenarioKey; onChangeScenario: (key: ScenarioKey) => void; onOpenScenarios?: () => void;
}) {
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = SCENARIOS.map(s => getForecastStats(period, s.key));
  const current = stats[SCENARIOS.findIndex(s => s.key === selected)]!;
  const cells = [
    { label: "Остаток через 30 дней", value: (s: typeof current) => formatMoney(s.last), delta: formatMoney(current.last - stats[0].last) },
    { label: "Минимальный остаток", value: (s: typeof current) => formatMoney(s.minimum), delta: formatMoney(current.minimum - stats[0].minimum) },
    { label: "Дней с дефицитом", value: (s: typeof current) => `${s.negativeDays} дн.`, delta: `${current.negativeDays - stats[0].negativeDays} дн.` },
    { label: "Максимальная нехватка", value: (s: typeof current) => formatMoney(s.deficit), delta: formatMoney(current.deficit - stats[0].deficit) },
    { label: "Первый кассовый разрыв", value: (s: typeof current) => s.firstNegative < 0 ? "Нет" : displayDate(period[s.firstNegative].date), delta: "—" },
  ];
  const colors: Record<ScenarioKey, string> = { base: "bg-[color:var(--puls-purple-bg)] text-[color:var(--puls-purple-text)]", delay: "bg-[color:var(--puls-good-bg)] text-[color:var(--puls-good-text)]", downturn: "bg-[color:var(--puls-demo-bg)] text-[color:var(--puls-demo-text)]" };
  return <section aria-label="Сравнение финансовых сценариев" className="mt-10 min-w-0">
    <header className="mb-4 flex items-start justify-between gap-3">
      <div><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Сравнение сценариев</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">Как изменения условий влияют на остаток денежных средств</p></div>
      {onOpenScenarios && <div className="flex shrink-0 items-center gap-2">
        <Button type="button" variant="outline" size="md" onClick={onOpenScenarios} disabled={!onOpenScenarios} className="bg-[color:var(--puls-purple-bg)]! text-[color:var(--puls-purple-text)]! [--button-outline-shadow:inset_0_0_0_1px_var(--puls-purple-border)] hover:bg-[color:var(--puls-purple-hover)]!"><Sparkles aria-hidden="true"/>Анализ</Button>
        <Button type="button" variant="outline" size="icon" aria-label="Открыть настройки сценариев" onClick={onOpenScenarios} disabled={!onOpenScenarios} className="text-[color:var(--puls-text-muted)]! [--button-outline-shadow:inset_0_0_0_1px_var(--puls-border)]"><SlidersHorizontal aria-hidden="true"/></Button>
      </div>}
    </header>
    <div className="w-full overflow-x-auto border-t border-[color:var(--puls-border)]">
      <Table unstyled className="w-full min-w-[790px] table-fixed border-separate border-spacing-0 text-[12px] text-[color:var(--puls-text-secondary)] tabular-nums">
        <TableHeader unstyled><TableRow unstyled>
          <TableHead unstyled className="w-[26%] border-r border-b border-[color:var(--puls-border-strong)] border-r-[color:var(--puls-border)] px-2.5 py-2 text-left font-normal text-[color:var(--puls-text-muted)]">Показатель</TableHead>
          {SCENARIOS.map(s => <TableHead unstyled key={s.key} className="border-r border-b border-[color:var(--puls-border-strong)] border-r-[color:var(--puls-border)] px-1.5 py-1.5 text-left font-normal">
            <Button type="button" variant="ghost" disabled={!scenarioSupported(data, s.key)} aria-pressed={selected === s.key} onClick={() => onChangeScenario(s.key)} className={`h-auto! inline-flex max-w-full cursor-pointer items-center gap-1.5! rounded-[4px]! border px-1.5 py-1 text-[12px] font-medium whitespace-nowrap text-[color:var(--puls-text-secondary)] hover:bg-[color:var(--puls-surface-active)] focus-visible:outline-2 focus-visible:outline-[color:var(--focus-ring-strong)] disabled:cursor-not-allowed disabled:opacity-35 ${selected === s.key ? "border-[color:var(--puls-border)] bg-[color:var(--puls-surface-active)]" : "border-transparent"}`}>
              <span className={`flex size-[17px] shrink-0 items-center justify-center rounded-[3px] ${colors[s.key]}`}><Activity size={13}/></span>{s.label}
            </Button>
          </TableHead>)}
          <TableHead unstyled className="border-b border-[color:var(--puls-border-strong)] px-2.5 py-2 text-right font-normal text-[color:var(--puls-text-muted)]">Δ к базовому</TableHead>
        </TableRow></TableHeader>
        <TableBody>{cells.map((row, rowIndex) => <TableRow unstyled key={row.label} className="odd:bg-[color:var(--puls-surface-muted)] hover:bg-[color:var(--puls-surface-active)]">
          <TableHead unstyled scope="row" className={`py-0 h-[40px] border-r border-b border-r-[color:var(--puls-border-strong)] border-b-[color:var(--puls-border)] px-3 text-left font-normal text-[color:var(--puls-text-secondary)] ${rowIndex === 0 ? "border-l-2 border-l-[color:var(--puls-text)]" : ""}`}>{row.label}{rowIndex === 1 && <span className="float-right text-[color:var(--puls-text-strong)]">✦</span>}</TableHead>
          {SCENARIOS.map((scenario, index) => <TableCell unstyled key={scenario.key} className={`py-0 h-[40px] border-r border-b border-r-[color:var(--puls-border)] border-b-[color:var(--puls-border)] px-2.5 text-right font-medium whitespace-nowrap ${selected === scenario.key ? "bg-[color:var(--puls-surface-active)]" : ""}`}>{scenarioSupported(data, scenario.key) ? row.value(stats[index]) : "—"}</TableCell>)}
          <TableCell unstyled className="py-0 h-[40px] border-b border-[color:var(--puls-border)] px-2.5 text-right whitespace-nowrap text-[color:var(--puls-text-secondary)]">{row.delta}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
    <p className="mt-2.5 flex items-center gap-1.5 text-[11px] text-[color:var(--puls-text-faint)]"><CircleHelp size={14}/>Нажми на сценарий в таблице, чтобы переключить график.</p>
  </section>;
}

export function PulsEmptyState({ onAddSource }: { onAddSource?: () => void }) {
  return <section className="mt-5 flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-[color:var(--puls-border)] p-7 text-center">
    <div className="flex size-[58px] items-center justify-center rounded-xl bg-[color:var(--puls-good-bg)] text-[color:var(--puls-good-text)]"><Activity size={27}/></div>
    <h2 className="mt-4 text-[20px] font-semibold tracking-tight text-[color:var(--puls-text)]">Для прогноза нужны операции и остаток на счёте</h2>
    <p className="mt-2 max-w-[440px] text-[13px] leading-relaxed text-[color:var(--puls-text-secondary)]">Если операции уже загружены, добавьте выписку с остатком на последнюю дату. После этого здесь появится прогноз на 30 дней и финансовые показатели.</p>
    {onAddSource && <Button type="button" variant="ghost" onClick={onAddSource} className="mt-4 h-auto! border-0! inline-flex cursor-pointer items-center gap-1.5! rounded-md! bg-[color:var(--brand)]! px-3.5! py-2.5! text-[12px] font-semibold! text-[color:var(--button-primary-fg)]! hover:text-[color:var(--button-primary-fg)]! hover:bg-[color:var(--brand-hover)]! focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--focus-ring-strong)]"><Plus size={15} className="size-[15px]!"/>Добавить источник данных</Button>}
  </section>;
}

export default function PulsOverview({ data = PULS_DEMO_DATA, onAddSource, onOpenForecast, onOpenCalendar, onOpenEvent, onOpenScenarios, onOpenGap, onOpenDay, alerts = [], horizon: controlledHorizon, onChangeHorizon }: PulsOverviewProps) {
  const [requested, setRequested] = useState<ScenarioKey>("base");
  const [localHorizon, setLocalHorizon] = useState<30 | 60 | 90>(30);
  const horizon = controlledHorizon ?? localHorizon;
  const setHorizon = onChangeHorizon ?? setLocalHorizon;
  const prepared = useMemo(() => data && data.forecast.length > 0 ? data : null, [data]);
  const selected = prepared && scenarioSupported(prepared, requested) ? requested : "base";
  return <div className="puls-overview min-w-0 w-full bg-[color:var(--puls-bg)] pb-10 text-[color:var(--puls-text)] tabular-nums">
    {prepared ? <>
      <div className="mb-3 flex min-h-[24px] flex-wrap items-center justify-end gap-3">
        {prepared.isDemo && <span className="inline-flex items-center gap-1.5 rounded-[5px] border border-[color:var(--puls-demo-border)] bg-[color:var(--puls-demo-bg)] px-2 py-0.5 text-[11px] text-[color:var(--puls-demo-text)]"><span className="size-1.5 rounded-full bg-[color:var(--puls-demo-text)]"/>Демо-данные</span>}
        <span className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--puls-text-muted)]"><Clock3 size={13}/>{prepared.updatedAt ?? `Прогноз на ${horizon} дней`}</span>
      </div>
      <FinancialStatus data={prepared} onOpenGap={onOpenGap}/>
      <KpiStrip data={prepared} selected={selected}/>
      <ForecastChart data={prepared} selected={selected} horizon={horizon} onChangeHorizon={setHorizon} onChangeScenario={setRequested} onOpenForecast={onOpenForecast} onOpenDay={onOpenDay}/>
      <NearTermFlows data={prepared} onOpenCalendar={onOpenCalendar} onOpenEvent={onOpenEvent}/>
      {prepared.isDemo ? <DemoWarnings data={prepared} selected={selected} onOpenGap={onOpenGap} onOpenCalendar={onOpenCalendar}/> : <OverviewAlerts alerts={alerts}/>}
      <OverviewPreviews data={prepared} selected={selected} onChangeScenario={setRequested} onOpenCalendar={onOpenCalendar} onOpenScenarios={onOpenScenarios}/>
      <p className="mt-6 text-[10px] leading-[18px] text-[color:var(--puls-text-faint)]">{prepared.isDemo ? "Синтетические демонстрационные данные. Числа не являются прогнозом реальной компании." : "Прогноз построен на загруженных данных; точность зависит от полноты информации и качества модели."}</p>
    </> : <><PulsEmptyState onAddSource={onAddSource}/><OverviewAlerts alerts={alerts}/></>}
  </div>;
}
