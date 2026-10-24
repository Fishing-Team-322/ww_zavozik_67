"use client";
import { ContentHeading, ContentText, contentTypography } from "@/src/shared/ui/content";
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
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  ChevronLeft,
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
import { SectionCard } from "@/src/widgets/cabinet-shell/ui/SectionCard";
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
  const days = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(days, selected);
  const minimum = selected === "base" && data.minimumBalance
    ? data.minimumBalance.p50
    : stats.minimum;
  const minimumDate = selected === "base" && data.minimumBalance
    ? data.minimumBalance.date
    : days.find((point) => (point[selected] ?? point.base) === minimum)?.date;
  const spendable = data.isDemo
    ? Math.max(0, Math.min(data.currentBalance, getForecastStats(days, "base").minimum - (data.reserve ?? 0)))
    : data.safeToSpend;
  const reserveDifference = data.reserve == null ? null : minimum - data.reserve;
  const change = stats.last - data.currentBalance;

  const items = [
    {
      label: "Текущий баланс",
      value: compactMoney(data.currentBalance),
      detail: data.reserve != null ? `Резерв ${compactMoney(data.reserve)}` : "На счетах компании",
      foot: "На текущую дату",
      alert: false,
    },
    {
      label: "Можно потратить сегодня",
      value: spendable == null ? "Нет оценки" : compactMoney(spendable),
      detail: "С учётом резерва и рисков",
      foot: "По базовому прогнозу",
      alert: false,
    },
    {
      label: "Минимальный остаток",
      value: compactMoney(minimum),
      detail: reserveDifference == null
        ? "Минимум за период"
        : reserveDifference < 0
          ? `Ниже резерва на ${compactMoney(-reserveDifference)}`
          : `Выше резерва на ${compactMoney(reserveDifference)}`,
      foot: minimumDate ? displayDate(minimumDate) : "За выбранный период",
      alert: minimum < 0,
    },
    {
      label: `Через ${data.horizon ?? 30} дней`,
      value: compactMoney(stats.last),
      detail: `${change > 0 ? "+" : ""}${compactMoney(change)} к текущему`,
      foot: selected === "base" ? "Базовый прогноз" : "Выбранный сценарий",
      alert: stats.last < 0,
    },
  ];

  return (
    <section
      aria-label="Ключевые показатели"
      className="grid grid-cols-2 border border-[color:var(--puls-border)] bg-[color:var(--puls-bg)] xl:grid-cols-4"
    >
      {items.map((item, index) => (
        <div
          key={item.label}
          className={[
            "flex min-h-[120px] min-w-0 flex-col px-3.5 py-3 sm:px-4",
            "border-[color:var(--puls-border)]",
            index < 2 ? "border-b xl:border-b-0" : "",
            index % 2 === 0 ? "border-r" : "",
            index !== 3 ? "xl:border-r" : "xl:border-r-0",
          ].join(" ")}
        >
          <ContentText as="span" variant="meta">
            {item.label}
          </ContentText>
          <strong
            className={`mt-2 ${contentTypography.kpi} ${
              item.alert ? "text-[color:var(--puls-negative-text)]" : "text-[color:var(--puls-text-strong)]"
            }`}
          >
            {item.value}
          </strong>
          <div className="mt-auto border-t border-[color:var(--puls-border)] pt-2">
            <ContentText variant="description" >{item.detail}</ContentText>
            <ContentText variant="description" className="mt-0.5">
              {item.foot}
            </ContentText>
          </div>
        </div>
      ))}
    </section>
  );
}

function FinancialStatus({ data, onOpenGap }: { data: PulsOverviewData; onOpenGap?: () => void }) {
  const days = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(days, "base");
  const firstGap = stats.firstNegative >= 0 ? days[stats.firstNegative] : null;
  const mappedStatus: Record<string, "ok" | "warning" | "danger" | "unknown"> = {
    ok: "ok",
    warning: "warning",
    danger: "danger",
  };
  const status = data.serverStatus
    ? (mappedStatus[data.serverStatus] ?? "unknown")
    : (firstGap ? "danger" : "ok");
  const risk = status === "danger";
  const warning = status === "warning";
  const headline = status === "ok" ? "Без критических рисков" :
    risk ? "Есть риск нехватки денег" :
    warning ? "Требует внимания" : "Статус не определён";
  const color = risk
    ? "text-[color:var(--puls-negative-text)]"
    : warning
      ? "text-[color:var(--puls-demo-text)]"
      : "text-[color:var(--puls-text)]";
  const marker = risk
    ? "border-l-[color:var(--puls-negative-text)]"
    : warning
      ? "border-l-[color:var(--puls-demo-text)]"
      : "border-l-[color:var(--puls-chart-primary)]";
  const riskPercent = data.shortfallProbability != null &&
    Number.isFinite(data.shortfallProbability) &&
    data.shortfallProbability >= 0 && data.shortfallProbability <= 1
      ? `${Math.round(data.shortfallProbability * 100)}%`
      : null;

  return (
    <section aria-label="Финансовое состояние" className="mb-7 min-w-0 border-y border-[color:var(--puls-border)] py-3">
      <div className={`flex min-w-0 flex-col gap-3 border-l-2 pl-3 sm:flex-row sm:items-center sm:justify-between ${marker}`}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className={`inline-flex items-center gap-1.5 text-[13px] font-semibold ${color}`}>
              {risk || warning ? <AlertTriangle size={14} aria-hidden="true" /> : <Activity size={14} aria-hidden="true" />}
              {headline}
            </span>
            {riskPercent && (
              <span className="text-[11px] text-[color:var(--puls-text-secondary)]">
                Вероятность разрыва: <strong className="font-semibold tabular-nums">{riskPercent}</strong>
              </span>
            )}
            {data.isDemo && (
              <span className="text-[11px] text-[color:var(--puls-demo-text)]">Демо-данные</span>
            )}
          </div>
          <ContentText variant="description" className="mt-1">
            {data.headline || (firstGap
              ? `По базовому прогнозу с ${displayDate(firstGap.date)} возможен отрицательный остаток. Максимальная нехватка — ${formatMoney(stats.deficit)}.`
              : "В выбранном периоде отрицательный остаток не прогнозируется.")}
          </ContentText>
        </div>
        {onOpenGap && (risk || warning || firstGap) && (
          <Button type="button" variant="outline" size="sm" onClick={onOpenGap} className="shrink-0">
            Разобрать риск <ChevronRight size={14} aria-hidden="true" />
          </Button>
        )}
      </div>
    </section>
  );
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
export function ForecastChart({ data, selected, horizon, onChangeHorizon, onChangeScenario, onOpenForecast, onOpenScenarios, onOpenDay }: {
  data: PulsOverviewData;
  selected: ScenarioKey;
  horizon: 30 | 60 | 90;
  onChangeHorizon: (value: 30 | 60 | 90) => void;
  onChangeScenario: (key: ScenarioKey) => void;
  onOpenForecast?: () => void;
  onOpenScenarios?: () => void;
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
  return <SectionCard aria-label="Прогноз денежных средств" className="mt-9">
    <header className="mb-3 flex flex-wrap items-start justify-between gap-x-5 gap-y-3">
      <div><ContentHeading level={2} >Финансовый прогноз <span className="font-normal text-[color:var(--puls-text-faint)]">/ {horizon} дней</span></ContentHeading><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">История, {data.isDemo ? "демо-коридор" : "прогнозный коридор"} и сравнение сценариев</p></div>
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
        {onOpenScenarios && <Button type="button" variant="ghost" size="sm" onClick={onOpenScenarios}>Все сценарии <ChevronRight size={14} aria-hidden="true" /></Button>}
        {onOpenForecast && <Button type="button" variant="outline" size="icon" aria-label="Открыть полный прогноз" onClick={onOpenForecast} ><ArrowUpRight aria-hidden="true" /></Button>}
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
    <div className="h-[255px] w-full min-w-0 border-b border-[color:var(--puls-border)] sm:h-[285px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartPoints} margin={{ top: 9, right: 8, bottom: 2, left: 0 }} onClick={state => {
          const pointDate = state?.activePayload?.map(item => item.payload).find(point => point && visible.some(day => day.date === point.date))?.date;
          const date = pointDate ?? state?.activeLabel;
          if (typeof date === "string" && visible.some(point => point.date === date)) onOpenDay?.(date);
        }}>
          <defs>
            <linearGradient id={`${reactId}-base`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-primary)" stopOpacity={0.17}/><stop offset="1" stopColor="var(--puls-chart-primary)" stopOpacity={0}/></linearGradient>
            <linearGradient id={`${reactId}-alt`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-secondary)" stopOpacity={0.13}/><stop offset="1" stopColor="var(--puls-chart-secondary)" stopOpacity={0}/></linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--puls-grid)" strokeDasharray="3 5"/>
          <XAxis dataKey="date" ticks={ticks} tickFormatter={displayDate} tickLine={false} axisLine={false} fontSize={11} dy={10} tick={{ fill: "var(--puls-text-muted)" }}/>
          <YAxis width={62} tickLine={false} axisLine={false} fontSize={11} tick={{ fill: "var(--puls-text-muted)" }} tickFormatter={formatAxisMoney}/>
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
    {onOpenDay && <p className="mt-2 text-[11px] text-[color:var(--puls-text-muted)]">Наведите на день и нажмите на график, чтобы открыть подробности.</p>}
  </SectionCard>;
}
function formatAxisMoney(value: number) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} млн`;
  if (abs >= 1_000) return `${Math.round(value / 1_000).toLocaleString("ru-RU")} тыс.`;
  return Math.round(value).toLocaleString("ru-RU");
}

function sourceLabel(value?: string) {
  const names: Record<string, string> = {
    manual: "Ручное событие",
    recurring: "Регулярный платёж",
    invoice: "Счёт",
    statement: "Банковская выписка",
  };
  return value ? (names[value] ?? value) : "Источник не указан";
}

function NearTermFlows({ data, onOpenCalendar, onOpenEvent }: { data: PulsOverviewData; onOpenCalendar?: () => void; onOpenEvent?: (id: string) => void }) {
  const events = data.events.filter(event => event.day >= 0 && event.day <= 14 && data.forecast[event.day]).sort((a, b) => a.day - b.day);
  const groups = [
    { title: "Ближайшие платежи", items: events.filter(event => event.amount < 0), color: "text-[color:var(--puls-text-strong)]" },
    { title: "Ожидаемые поступления", items: events.filter(event => event.amount > 0), color: "text-[color:var(--puls-positive-text)]" },
  ];
  return <SectionCard className="mt-8 grid gap-5 lg:grid-cols-2 lg:gap-7">
    {groups.map(group => <section key={group.title} className="min-w-0">
      <header className="flex items-center justify-between gap-3 py-3"><div><ContentHeading level={2} >{group.title}</ContentHeading><ContentText variant="description" className="mt-0.5">На ближайшие 14 дней</ContentText></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" onClick={onOpenCalendar}>Календарь <ChevronRight aria-hidden="true"/></Button>}</header>
      <Table className="min-w-[440px]"><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead>Платёж</TableHead><TableHead numeric>Сумма</TableHead></TableRow></TableHeader><TableBody>{group.items.length ? group.items.slice(0, 4).map(event => <TableRow key={event.id}>
        <TableCell className="whitespace-nowrap text-[color:var(--puls-text-secondary)]">{displayDate(data.forecast[event.day].date)}</TableCell>
        <TableCell className="min-w-[140px] max-w-[260px]"><div className="truncate font-medium" title={event.title}>{onOpenEvent ? <button type="button" className="max-w-full truncate align-bottom text-left underline decoration-transparent underline-offset-2 hover:text-[color:var(--accent)] hover:decoration-current focus-visible:outline-2 focus-visible:outline-[color:var(--accent)]" onClick={() => onOpenEvent(event.id)}>{event.title}</button> : event.title}</div><div className="truncate text-[12px] text-[color:var(--puls-text-secondary)]" title={event.counterparty ?? undefined}>{event.counterparty ?? "Контрагент не указан"}</div></TableCell>
        <TableCell numeric className={`whitespace-nowrap font-medium tabular-nums ${group.color}`}>{event.amount > 0 ? "+" : ""}{formatMoney(event.amount)}</TableCell>
      </TableRow>) : <TableRow><TableCell colSpan={3} tone="muted">Событий на ближайшие 14 дней нет.</TableCell></TableRow>}</TableBody></Table>
    </section>)}
  </SectionCard>;
}
function WarningCarousel({ items, footer }: { items: ReactNode[]; footer?: ReactNode }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [canScrollBack, setCanScrollBack] = useState(false);
  const [canScrollForward, setCanScrollForward] = useState(false);
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const update = () => {
      setCanScrollBack(viewport.scrollLeft > 1);
      setCanScrollForward(viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1);
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [items.length]);
  if (!items.length) return null;
  return <SectionCard className="mt-9">
    <header className="mb-4 flex items-center justify-between gap-3"><div><ContentHeading level={2}>Предупреждения</ContentHeading><ContentText variant="description" className="mt-0.5">События, которые стоит проверить</ContentText></div><div className="flex shrink-0 gap-1"><Button type="button" variant="outline" size="icon" aria-label="Предыдущие предупреждения" disabled={!canScrollBack} onClick={() => viewportRef.current?.scrollBy({ left: -316, behavior: "smooth" })}><ChevronLeft aria-hidden="true" /></Button><Button type="button" variant="outline" size="icon" aria-label="Следующие предупреждения" disabled={!canScrollForward} onClick={() => viewportRef.current?.scrollBy({ left: 316, behavior: "smooth" })}><ChevronRight aria-hidden="true" /></Button></div></header>
    <div ref={viewportRef} onScroll={event => { const viewport = event.currentTarget; setCanScrollBack(viewport.scrollLeft > 1); setCanScrollForward(viewport.scrollLeft + viewport.clientWidth < viewport.scrollWidth - 1); }} className="flex snap-x snap-mandatory gap-3 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">{items}</div>
    {footer}
  </SectionCard>;
}
function OverviewAlerts({ alerts }: { alerts: Schemas["Alert"][] }) {
  const priority = (severity: string) => severity === "danger" || severity === "critical" ? 0 : severity === "warning" ? 1 : 2;
  const ordered = [...alerts].sort((first, second) => priority(first.severity) - priority(second.severity));
  return <WarningCarousel items={ordered.map(alert => <article key={alert.id} className="flex min-h-36 w-[300px] shrink-0 snap-start flex-col rounded-md border border-[color:var(--puls-border)] p-3 text-[13px]"><div className="flex items-start gap-2"><AlertTriangle size={16} aria-label={priority(alert.severity) === 0 ? "Опасно" : alert.severity === "warning" ? "Внимание" : "Информация"} className={`mt-0.5 shrink-0 ${priority(alert.severity) === 0 ? "text-[color:var(--puls-chart-zero)]" : alert.severity === "warning" ? "text-[color:var(--puls-demo-text)]" : "text-[color:var(--puls-text-secondary)]"}`} /><div className="min-w-0"><strong className="font-medium text-[color:var(--puls-text)]">{alert.title}</strong>{!alert.read && <span className="ml-2 text-[11px] text-[color:var(--puls-text-muted)]">Новое</span>}<ContentText variant="description" className="mt-1 line-clamp-3" title={alert.body}>{alert.body}</ContentText></div></div><Link href={alertLink(alert.ref)} className="mt-auto inline-flex items-center gap-1 self-start pt-3 text-[12px] text-[color:var(--puls-text-secondary)] underline underline-offset-2">Подробнее <ChevronRight size={12} aria-hidden="true" /></Link></article>)} footer={alerts.length > 0 && <Link href="/notifications" className="mt-3 inline-flex items-center gap-1 text-[12px] text-[color:var(--puls-text-secondary)] hover:text-[color:var(--puls-text)]">Все уведомления ({alerts.length}) <ChevronRight size={13} /></Link>} />;
}
function DemoWarnings({ data, selected, onOpenGap, onOpenCalendar }: { data: PulsOverviewData; selected: ScenarioKey; onOpenGap?: () => void; onOpenCalendar?: () => void }) {
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  const stats = getForecastStats(period, selected);
  const firstGap = stats.firstNegative >= 0 ? period[stats.firstNegative] : null;
  const unusual = data.events.filter(event => data.unusualExpenseIds?.includes(event.id) && event.amount < 0);
  const overdue = data.overdueReceipts ?? [];
  if (!firstGap && overdue.length === 0 && unusual.length === 0) return null;
  const cardClassName = "flex min-h-36 w-[300px] shrink-0 snap-start flex-col rounded-md border border-[color:var(--puls-border)] p-3 text-[13px]";
  return <WarningCarousel items={[
    ...(firstGap ? [<article key="gap" className={cardClassName}><div className="flex items-start gap-2"><AlertTriangle size={16} className="mt-0.5 shrink-0 text-[color:var(--puls-chart-zero)]"/><div className="min-w-0"><strong className="font-medium text-[color:var(--puls-text)]">Возможная нехватка денег · {displayDate(firstGap.date)}</strong><ContentText variant="description" className="mt-1">Максимальный дефицит: {formatMoney(stats.deficit)}</ContentText></div></div>{onOpenGap && <Button type="button" variant="ghost" size="sm" className="mt-auto self-start" onClick={onOpenGap}>Подробнее <ChevronRight aria-hidden="true"/></Button>}</article>] : []),
    ...overdue.map(item => <article key={`${item.dueDate}-${item.counterparty}`} className={cardClassName}><div className="flex items-start gap-2"><Clock3 size={16} className="mt-0.5 shrink-0 text-[color:var(--puls-demo-text)]"/><div className="min-w-0"><strong className="font-medium text-[color:var(--puls-text)]">Просроченное поступление · {item.counterparty}</strong><ContentText variant="description" className="mt-1">{item.title}: {formatMoney(item.amount)}, срок {displayDate(item.dueDate)}. Не включено в прогноз.</ContentText></div></div></article>),
    ...unusual.map(event => <article key={event.id} className={cardClassName}><div className="flex items-start gap-2"><Activity size={16} className="mt-0.5 shrink-0 text-[color:var(--puls-demo-text)]"/><div className="min-w-0"><strong className="font-medium text-[color:var(--puls-text)]">Необычное списание · {event.title}</strong><ContentText variant="description" className="mt-1">{event.counterparty ?? "Контрагент не указан"} · {data.forecast[event.day] ? displayDate(data.forecast[event.day].date) : `День ${event.day}`} · {formatMoney(event.amount)}{data.isDemo ? " · демо-метка" : ""}</ContentText></div></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" className="mt-auto self-start" onClick={onOpenCalendar}>Календарь <ChevronRight aria-hidden="true"/></Button>}</article>),
  ]} />;
}
function OverviewPreviews({ data, selected, onChangeScenario, onOpenCalendar, onOpenScenarios }: {
  data: PulsOverviewData;
  selected: ScenarioKey;
  onChangeScenario: (key: ScenarioKey) => void;
  onOpenCalendar?: () => void;
  onOpenScenarios?: () => void;
}) {
  const near = data.events.filter(event => event.day >= 0 && event.day <= 14);
  const calendarEvents = near.filter(event => data.forecast[event.day]).sort((a, b) => a.day - b.day).slice(0, 5);
  const period = data.forecast.slice(0, (data.horizon ?? 30) + 1);
  return <SectionCard className="mt-11 grid gap-5 lg:grid-cols-2 lg:gap-7">
    <section aria-label="Превью платёжного календаря" className="min-w-0">
      <header className="flex items-center justify-between gap-3 py-3"><div><ContentHeading level={2} >Платёжный календарь</ContentHeading><ContentText variant="description" className="mt-0.5">План на ближайшие 14 дней</ContentText></div>{onOpenCalendar && <Button type="button" variant="ghost" size="sm" onClick={onOpenCalendar}>Открыть <ChevronRight aria-hidden="true"/></Button>}</header>
      <Table className="min-w-[440px]"><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead>Событие</TableHead><TableHead numeric>Сумма</TableHead></TableRow></TableHeader><TableBody>{calendarEvents.length ? calendarEvents.map(event => <TableRow key={event.id}>
        <TableCell className="whitespace-nowrap text-[color:var(--puls-text-secondary)]">{displayDate(data.forecast[event.day].date)}</TableCell>
        <TableCell className="min-w-[140px] max-w-[260px]"><div className="truncate font-medium" title={event.title}>{event.title}</div><div className="truncate text-[12px] text-[color:var(--puls-text-secondary)]">{event.counterparty ?? sourceLabel(event.source)}</div></TableCell>
        <TableCell numeric className={`whitespace-nowrap font-medium tabular-nums ${event.amount > 0 ? "text-[color:var(--puls-positive-text)]" : "text-[color:var(--puls-text-strong)]"}`}>{event.amount > 0 ? "+" : ""}{formatMoney(event.amount)}</TableCell>
      </TableRow>) : <TableRow><TableCell colSpan={3} tone="muted">Событий на ближайшие 14 дней нет.</TableCell></TableRow>}</TableBody></Table>
    </section>
    <section aria-label="Превью сравнения сценариев" className="min-w-0">
      <header className="flex items-center justify-between gap-3 py-3"><div><ContentHeading level={2} >Сценарии</ContentHeading><ContentText variant="description" className="mt-0.5">Остаток в конце периода</ContentText></div>{onOpenScenarios && <Button type="button" variant="ghost" size="sm" onClick={onOpenScenarios}>Сравнить <ChevronRight aria-hidden="true"/></Button>}</header>
      <div className="divide-y divide-[color:var(--puls-border)] border-t border-[color:var(--puls-border)]">{SCENARIOS.filter(scenario => scenarioSupported(data, scenario.key)).map(scenario => {
        const stats = getForecastStats(period, scenario.key);
        return <Button variant="ghost" key={scenario.key} type="button" aria-pressed={selected === scenario.key} onClick={() => onChangeScenario(scenario.key)} className="w-full"><span className="min-w-0 truncate">{scenario.label}</span><strong className="shrink-0 font-medium tabular-nums text-[color:var(--puls-text-strong)]">{compactMoney(stats.last)}</strong></Button>;
      })}</div>
    </section>
  </SectionCard>;
}

export function PaymentTimeline({ data, onOpenCalendar }: { data: PulsOverviewData; onOpenCalendar?: () => void }) {
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const current = data.events.find(e => e.id === selectedEvent);
  const segments = Array.from({ length: 5 }, (_, i) => displayDate(data.forecast[Math.min(i * 6, data.forecast.length - 1)]?.date ?? ""));
  return <section aria-label="Календарь платежей" className="mt-10 min-w-0">
    <header className="mb-4 flex items-start justify-between gap-3">
      <div><ContentHeading level={2} >Календарь платежей</ContentHeading><ContentText variant="description" className="mt-0.5">Поступления и обязательные списания на временной шкале</ContentText></div>
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
              return <Button variant="ghost" key={event.id} type="button" title={`${event.title} · ${formatMoney(event.amount)} · ${event.source ?? "План"}`} aria-pressed={isCurrent} onClick={() => setSelectedEvent(isCurrent ? null : event.id)} style={{ left: `${leftPercent}%`, width: `${widthPercent}%` }} className="absolute top-[7px] z-10 min-w-[104px] max-w-full overflow-hidden">
                <span className={`flex size-[18px] shrink-0 items-center justify-center rounded-full ${event.amount >= 0 ? "bg-[color:var(--puls-positive-bg)] text-[color:var(--puls-positive-text)]" : "bg-[color:var(--puls-negative-bg)] text-[color:var(--puls-negative-text)]"}`}>{event.amount >= 0 ? <ArrowDownRight size={13}/> : <ArrowUpRight size={13}/>}</span>
                <span className="truncate">{event.title}</span>
              </Button>;
            })}
          </div>
        </div>)}
      </div>
    </div>
    {current ? <div className="mt-3 flex items-center gap-3 rounded-md border border-[color:var(--puls-border)] bg-[color:var(--puls-surface-soft)] px-3 py-2.5">
      <div className="mr-auto min-w-0"><p className="text-[12px] font-semibold text-[color:var(--puls-text)]">{current.title}</p><ContentText variant="description" className="mt-0.5">{displayDate(data.forecast[Math.max(0, Math.min(current.day, data.forecast.length - 1))].date)} · {current.source ?? "Плановое событие"}</ContentText></div>
      <strong className={`shrink-0 text-[13px] ${current.amount >= 0 ? "text-[color:var(--puls-positive-text)]" : "text-[color:var(--puls-text-strong)]"}`}>{current.amount > 0 ? "+" : ""}{formatMoney(current.amount)}</strong>
      <Button type="button" variant="ghost" size="icon" aria-label="Закрыть детали" onClick={() => setSelectedEvent(null)} className="shrink-0"><X size={17} className="size-[17px]!"/></Button>
    </div> : <ContentText variant="description" className="mt-2.5">Нажми на событие, чтобы посмотреть сумму, дату и источник данных.</ContentText>}
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
      <div><ContentHeading level={2} >Сравнение сценариев</ContentHeading><ContentText variant="description" className="mt-0.5">Как изменения условий влияют на остаток денежных средств</ContentText></div>
      {onOpenScenarios && <div className="flex shrink-0 items-center gap-2">
        <Button type="button" variant="outline" size="md" onClick={onOpenScenarios} disabled={!onOpenScenarios} ><Sparkles aria-hidden="true"/>Анализ</Button>
        <Button type="button" variant="outline" size="icon" aria-label="Открыть настройки сценариев" onClick={onOpenScenarios} disabled={!onOpenScenarios} ><SlidersHorizontal aria-hidden="true"/></Button>
      </div>}
    </header>
    <div className="w-full overflow-x-auto border-t border-[color:var(--puls-border)]">
      <Table variant="matrix" density="comfortable" className="min-w-[790px] table-fixed">
        <TableHeader><TableRow>
          <TableHead className="w-[26%]">Показатель</TableHead>
          {SCENARIOS.map(s => <TableHead key={s.key} numeric>
            <Button type="button" variant={selected === s.key ? "secondary" : "ghost"} disabled={!scenarioSupported(data, s.key)} aria-pressed={selected === s.key} onClick={() => onChangeScenario(s.key)}>
              <span className={`flex size-[17px] shrink-0 items-center justify-center rounded-[3px] ${colors[s.key]}`}><Activity size={13}/></span>{s.label}
            </Button>
          </TableHead>)}
          <TableHead numeric>Δ к базовому</TableHead>
        </TableRow></TableHeader>
        <TableBody>{cells.map((row, rowIndex) => <TableRow key={row.label}>
          <TableHead scope="row">{row.label}{rowIndex === 1 && <span className="float-right">✦</span>}</TableHead>
          {SCENARIOS.map((scenario, index) => <TableCell key={scenario.key} numeric highlighted={selected === scenario.key} className="whitespace-nowrap">{scenarioSupported(data, scenario.key) ? row.value(stats[index]) : "—"}</TableCell>)}
          <TableCell numeric tone="muted" className="whitespace-nowrap">{row.delta}</TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>
    <ContentText variant="description" className="mt-2.5 flex items-center gap-1.5"><CircleHelp size={14}/>Нажми на сценарий в таблице, чтобы переключить график.</ContentText>
  </section>;
}
export function PulsEmptyState({ onAddSource }: { onAddSource?: () => void }) {
  return <section className="mt-5 flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-[color:var(--puls-border)] p-7 text-center">
    <div className="flex size-[58px] items-center justify-center rounded-xl bg-[color:var(--puls-good-bg)] text-[color:var(--puls-good-text)]"><Activity size={27}/></div>
    <ContentHeading level={2} className="mt-4">Для прогноза нужны операции и остаток на счёте</ContentHeading>
    <ContentText variant="description" className="mt-2 max-w-[440px]">Если операции уже загружены, добавьте выписку с остатком на последнюю дату. После этого здесь появится прогноз на 30 дней и финансовые показатели.</ContentText>
    {onAddSource && <Button type="button" variant="ghost" onClick={onAddSource} className="mt-4"><Plus size={15} className="size-[15px]!"/>Добавить источник данных</Button>}
  </section>;
}
export default function PulsOverview({
  data = PULS_DEMO_DATA,
  onAddSource,
  onOpenForecast,
  onOpenCalendar,
  onOpenEvent,
  onOpenScenarios,
  onOpenGap,
  onOpenDay,
  alerts = [],
  horizon: controlledHorizon,
  onChangeHorizon,
}: PulsOverviewProps) {
  const [requested, setRequested] = useState<ScenarioKey>("base");
  const [localHorizon, setLocalHorizon] = useState<30 | 60 | 90>(30);
  const horizon = controlledHorizon ?? localHorizon;
  const setHorizon = onChangeHorizon ?? setLocalHorizon;
  const prepared = useMemo(
    () => (data && data.forecast.length > 0 ? data : null),
    [data],
  );
  const selected = prepared && scenarioSupported(prepared, requested)
    ? requested
    : "base";

  return (
    <div className={`puls-overview w-full min-w-0 bg-[color:var(--puls-bg)] pb-8 text-[color:var(--puls-text)] tabular-nums ${contentTypography.body}`}>
      <ContentHeading level={1} className="mb-6">Обзор</ContentHeading>
      {prepared ? (
        <>
          <div className="mb-3 flex flex-wrap items-center justify-end gap-3 text-[11px] text-[color:var(--puls-text-muted)]">
            {prepared.isDemo && <span className="text-[color:var(--puls-demo-text)]">Демо-данные</span>}
            <span className="inline-flex items-center gap-1.5"><Clock3 size={13}/>{prepared.updatedAt ?? `Прогноз на ${horizon} дней`}</span>
          </div>
          <FinancialStatus data={prepared} onOpenGap={onOpenGap} />
          <KpiStrip data={prepared} selected={selected} />
          <ForecastChart
            data={prepared}
            selected={selected}
            horizon={horizon}
            onChangeHorizon={setHorizon}
            onChangeScenario={setRequested}
            onOpenForecast={onOpenForecast}
            onOpenScenarios={onOpenScenarios}
            onOpenDay={onOpenDay}
          />
          {prepared.isDemo ? (
            <DemoWarnings
              data={prepared}
              selected={selected}
              onOpenGap={onOpenGap}
              onOpenCalendar={onOpenCalendar}
            />
          ) : (
            <OverviewAlerts alerts={alerts} />
          )}
          <NearTermFlows
            data={prepared}
            onOpenCalendar={onOpenCalendar}
            onOpenEvent={onOpenEvent}
          />
          <OverviewPreviews data={prepared} selected={selected} onChangeScenario={setRequested} onOpenCalendar={onOpenCalendar} onOpenScenarios={onOpenScenarios}/>
          <ContentText variant="description" className="mt-7 border-t border-[color:var(--puls-border)] pt-3">
            {prepared.isDemo
              ? "Синтетические демонстрационные данные. Это не прогноз реальной компании."
              : "Оценка основана на доступных финансовых данных. Фактические поступления и расходы могут отличаться от прогноза."}
          </ContentText>
        </>
      ) : (
        <>
          <PulsEmptyState onAddSource={onAddSource} />
          <OverviewAlerts alerts={alerts} />
        </>
      )}
    </div>
  );
}
