"use client";

/**
 * ПУЛЬС / Runway-inspired overview — pure TSX + Tailwind CSS.
 *
 * USAGE:  import PulsOverview from "@/src/components/puls/PulsOverview";
 *         <PulsOverview />             // synthetic, visibly marked example
 *         <PulsOverview data={null} /> // empty state until data is loaded
 *         <PulsOverview data={apiData} onAddSource={() => ...} />
 *
 * Rendered by the home page inside the persistent CabinetShell, below Breadcrumbs.
 * No CSS modules or extra stylesheet required.
 * All fictional data are labelled. Risk probability is never invented.
 */

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
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/src/components/ui/button";
import { Tabs } from "@/src/components/ui/tabs";

export type ScenarioKey = "base" | "delay" | "downturn";
export type EventCategory = "revenue" | "payroll" | "suppliers" | "taxes" | "other";

export type ForecastDay = {
  date: string; // YYYY-MM-DD, ideally 31 consecutive dates
  base: number; // projected EOD balance, RUB
  delay?: number; // balance after shifting a client payment
  downturn?: number; // balance after revenue downturn
  actual?: number | null;
};

export type CashEvent = {
  id: string;
  title: string;
  day: number; // days from the start of forecast (0..30)
  duration?: number; // display-only bar width; not a transaction duration
  category: EventCategory;
  amount: number; // income positive, costs negative
  counterparty?: string;
  source?: string;
};

export type PulsOverviewData = {
  company?: string;
  currentBalance: number;
  forecast: ForecastDay[];
  events: CashEvent[];
  shortfallProbability?: number | null; // Only supply statistically supported 0..1
  updatedAt?: string;
  isDemo?: boolean;
};

export type PulsOverviewProps = {
  data?: PulsOverviewData | null;
  onAddSource?: () => void;
  onOpenForecast?: () => void;
  onOpenCalendar?: () => void;
  onOpenScenarios?: () => void;
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
    { id: "e1", title: "ООО «Вектор»", day: 7, duration: 5, category: "revenue", amount: 180000, source: "Выставленный счёт" },
    { id: "e2", title: "ООО «Сфера»", day: 13, duration: 5, category: "revenue", amount: 240000, source: "Договор" },
    { id: "e3", title: "ООО «Маяк»", day: 22, duration: 5, category: "revenue", amount: 390000, source: "Выставленный счёт" },
    { id: "e4", title: "Зарплата", day: 15, duration: 5, category: "payroll", amount: -600000, source: "Зарплатный проект" },
    { id: "e5", title: "Аренда офиса", day: 3, duration: 5, category: "suppliers", amount: -100000, source: "Регулярный платёж" },
    { id: "e6", title: "Поставщик", day: 9, duration: 5, category: "suppliers", amount: -135000, source: "Счёт поставщика" },
    { id: "e7", title: "Налоги", day: 18, duration: 4, category: "taxes", amount: -120000, source: "Налоговый календарь" },
    { id: "e8", title: "Оборудование", day: 26, duration: 4, category: "other", amount: -145000, source: "Ручное событие" },
  ];
  let base = 470000;
  let delay = 470000;
  let downturn = 470000;
  const forecast: ForecastDay[] = [];
  const reference = new Date("2026-10-24T00:00:00Z");
  for (let day = 0; day <= 30; day += 1) {
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
    forecast.push({ date: d.toISOString().slice(0, 10), base: Math.round(base), delay: Math.round(delay), downturn: Math.round(downturn) });
  }
  return { currentBalance: 470000, company: "ООО «Горизонт»", forecast, events, isDemo: true };
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
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const stats = getForecastStats(data.forecast, selected);
  const base = data.forecast.map(p => p.base);
  const active = data.forecast.map(p => p[selected] ?? p.base);
  const baseFlows = data.forecast.map((point, i) => i === 0 ? 0 : point.base - data.forecast[i - 1].base);
  const selectedFlows = data.forecast.map((point, i) => i === 0 ? 0 : (point[selected] ?? point.base) - (data.forecast[i - 1][selected] ?? data.forecast[i - 1].base));
  const items = [
    { title: "Текущий остаток", value: compactMoney(data.currentBalance), hint: "На счету сегодня", a: base, b: active },
    { title: "Через 30 дней", value: compactMoney(stats.last), hint: "Прогнозный остаток", a: base, b: active },
    { title: "Минимальный остаток", value: compactMoney(stats.minimum), hint: "Нижняя точка за период", a: base, b: active },
    { title: "Первый кассовый разрыв", value: stats.firstNegative < 0 ? "Не ожидается" : displayDate(data.forecast[stats.firstNegative].date), hint: stats.firstNegative < 0 ? "По выбранному сценарию" : `Дефицит до ${compactMoney(stats.deficit)}`, a: baseFlows, b: selectedFlows },
  ];
  return <section aria-label="Ключевые показатели" className="grid grid-cols-2 border border-[color:var(--puls-border)] bg-[color:var(--puls-bg)] xl:grid-cols-4">
    {items.map((item, index) => <div key={item.title} className={`relative flex min-h-[148px] min-w-0 flex-col overflow-hidden border-[color:var(--puls-border)] xl:min-h-[164px] xl:border-r xl:border-b-0 xl:last:border-r-0 ${index < 2 ? "border-b" : ""} ${index % 2 === 0 ? "border-r" : ""}`}>
      <div className="relative z-10 flex min-h-[46px] items-start justify-between gap-2 px-3 pt-3 text-[12px] font-medium leading-[18px] text-[color:var(--puls-text)] sm:text-[13px]">
        <span>{item.title}</span>
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-right text-[12px] font-semibold text-[color:var(--puls-text-strong)] sm:text-[14px]">
          <span className="inline-block h-0 w-0 border-y-[4px] border-l-[8px] border-y-transparent border-l-[color:var(--puls-text-strong)] max-sm:hidden"/>
          {item.value}
        </span>
      </div>
      <KpiSparkline first={item.a} second={selected === "base" ? undefined : item.b} id={`${reactId}-${index}`}/>
      <p className="px-3 pb-2 text-[10px] leading-[15px] text-[color:var(--puls-text-faint)]">{item.hint}</p>
    </div>)}
  </section>;
}

function ForecastTooltip({ active, payload, label, rows, selected }: {
  active?: boolean;
  payload?: readonly unknown[];
  label?: string | number;
  rows: ForecastDay[];
  selected: ScenarioKey;
}) {
  if (!active || !payload?.length) return null;
  const day = rows.find(row => row.date === label);
  if (!day) return null;
  const currentScenario = SCENARIOS.find(s => s.key === selected)!;
  return <div className="min-w-[184px] rounded-md border border-[color:var(--puls-border)] bg-[color:var(--puls-bg)] p-3 text-[11px] text-[color:var(--puls-text-secondary)] shadow-[0_8px_28px_rgba(25,23,20,0.13)]">
    <strong className="mb-2 block text-[12px] text-[color:var(--puls-text)]">{displayDate(day.date)}</strong>
    <div className="flex items-center gap-2"><span className="size-1.5 rounded-full bg-[color:var(--puls-chart-primary)]"/>Базовый <b className="ml-auto text-[color:var(--puls-text-strong)]">{formatMoney(day.base)}</b></div>
    {selected !== "base" && <div className="mt-1.5 flex items-center gap-2"><span className="size-1.5 rounded-full bg-[color:var(--puls-chart-secondary)]"/>{currentScenario.label}<b className="ml-auto text-[color:var(--puls-text-strong)]">{formatMoney(day[selected] ?? day.base)}</b></div>}
  </div>;
}

export function ForecastChart({ data, selected, onChangeScenario, onOpenForecast }: {
  data: PulsOverviewData;
  selected: ScenarioKey;
  onChangeScenario: (key: ScenarioKey) => void;
  onOpenForecast?: () => void;
}) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const risk = getForecastStats(data.forecast, selected);
  const currentScenario = SCENARIOS.find(s => s.key === selected)!;
  const chartPoints = data.forecast.map(p => ({ ...p, selectedValue: p[selected] ?? p.base }));
  const ticks = chartPoints.filter((_, index) => index % 5 === 0 || index === chartPoints.length - 1).map(p => p.date);
  return <section aria-label="Прогноз денежных средств" className="mt-9 min-w-0">
    <header className="mb-4 flex flex-wrap items-start justify-between gap-x-5 gap-y-3">
      <div><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Финансовый прогноз <span className="font-normal text-[color:var(--puls-text-faint)]">/ 30 дней</span></h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">Остаток на конец дня · сравнение сценариев</p></div>
      <div className="flex max-w-full items-center gap-2">
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
      <span className="flex items-center gap-1.5"><span className="h-0.5 w-[20px] bg-[color:var(--puls-chart-primary)]"/>Базовый прогноз</span>
      {selected !== "base" && <span className="flex items-center gap-1.5"><span className="h-0.5 w-[20px] bg-[color:var(--puls-chart-secondary)]"/>{currentScenario.full}</span>}
      <span className="ml-auto flex items-center gap-1.5"><span className="w-[16px] border-t border-dashed border-[color:var(--puls-chart-zero)]"/>Нулевой остаток</span>
    </div>
    <div className="h-[265px] w-full min-w-0 border-b border-[color:var(--puls-border)] sm:h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={chartPoints} margin={{ top: 9, right: 8, bottom: 2, left: 0 }}>
          <defs>
            <linearGradient id={`${reactId}-base`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-primary)" stopOpacity={0.17}/><stop offset="1" stopColor="var(--puls-chart-primary)" stopOpacity={0}/></linearGradient>
            <linearGradient id={`${reactId}-alt`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--puls-chart-secondary)" stopOpacity={0.13}/><stop offset="1" stopColor="var(--puls-chart-secondary)" stopOpacity={0}/></linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--puls-grid)" strokeDasharray="3 5"/>
          <XAxis dataKey="date" ticks={ticks} tickFormatter={displayDate} tickLine={false} axisLine={false} fontSize={11} dy={10} tick={{ fill: "var(--puls-text-muted)" }}/>
          <YAxis width={62} tickLine={false} axisLine={false} fontSize={11} tick={{ fill: "var(--puls-text-muted)" }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}/>
          <Tooltip cursor={{ stroke: "var(--puls-text-muted)", strokeDasharray: "4 4" }} content={({ active, payload, label }) => <ForecastTooltip active={active} payload={payload} label={label} rows={data.forecast} selected={selected}/>}/>
          <ReferenceLine y={0} stroke="var(--puls-chart-zero)" strokeDasharray="5 5" strokeWidth={1.2}/>
          {risk.firstNegative >= 0 && <ReferenceLine x={data.forecast[risk.firstNegative].date} stroke="var(--puls-chart-zero)" strokeDasharray="3 5"/>}
          <Area type="monotone" dataKey="base" fill={`url(#${reactId}-base)`} stroke="none" isAnimationActive={false} tooltipType="none"/>
          {selected !== "base" && <Area type="monotone" dataKey="selectedValue" fill={`url(#${reactId}-alt)`} stroke="none" isAnimationActive={false} tooltipType="none"/>}
          <Line type="monotone" name="Базовый" dataKey="base" stroke="var(--puls-chart-primary)" strokeWidth={2.1} dot={false} activeDot={{ r: 4, fill: "var(--puls-chart-primary)", stroke: "var(--puls-bg)", strokeWidth: 2 }} isAnimationActive={false}/>
          {selected !== "base" && <Line type="monotone" name={currentScenario.full} dataKey="selectedValue" stroke="var(--puls-chart-secondary)" strokeWidth={2} strokeDasharray="6 4" dot={false} activeDot={{ r: 4, fill: "var(--puls-chart-secondary)", stroke: "var(--puls-bg)", strokeWidth: 2 }} isAnimationActive={false}/>}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <div className={`mt-3 flex items-start gap-2.5 rounded-md border px-3.5 py-3 ${risk.firstNegative < 0 ? "border-[color:var(--puls-good-border)] bg-[color:var(--puls-good-bg)]" : "border-[color:var(--puls-risk-border)] bg-[color:var(--puls-risk-bg)]"}`}>
      {risk.firstNegative < 0 ? <Activity size={18} className="mt-0.5 shrink-0 text-[color:var(--puls-good-text)]"/> : <AlertTriangle size={18} className="mt-0.5 shrink-0 text-[color:var(--puls-risk-text)]"/>}
      <div className="min-w-0 flex-1">
        <p className={`text-[12px] font-semibold ${risk.firstNegative < 0 ? "text-[color:var(--puls-good-text)]" : "text-[color:var(--puls-risk-text)]"}`}>{risk.firstNegative < 0 ? "Кассовых разрывов по сценарию не выявлено" : `Возможен кассовый разрыв ${displayDate(data.forecast[risk.firstNegative].date)}`}</p>
        <p className={`mt-0.5 text-[11px] leading-[17px] ${risk.firstNegative < 0 ? "text-[color:var(--puls-good-muted)]" : "text-[color:var(--puls-risk-muted)]"}`}>{risk.firstNegative < 0 ? "При выбранных условиях прогнозный остаток не опускается ниже нуля." : `Минимальный остаток ${formatMoney(risk.minimum)}. Возможная нехватка денег — ${formatMoney(risk.deficit)}.`}</p>
      </div>
      {selected === "base" && data.shortfallProbability != null && Number.isFinite(data.shortfallProbability) && data.shortfallProbability >= 0 && data.shortfallProbability <= 1 && <span className="shrink-0 text-[11px] font-semibold text-[color:var(--puls-risk-text)]">Риск {Math.round(data.shortfallProbability * 100)}%</span>}
    </div>
  </section>;
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
          <div className="flex min-w-0 items-center gap-1.5 border-r border-b border-dashed border-[color:var(--puls-border-strong)] px-2 text-[12px] text-[color:var(--puls-text-secondary)] last:border-b-0"><ChevronRight size={14} className="shrink-0 text-[#817e75]"/>{label}</div>
          <div className={`relative min-w-0 overflow-hidden border-b border-[color:var(--puls-border)] ${rowIndex % 2 === 0 ? "bg-[color:var(--puls-surface-soft)]" : "bg-[color:var(--puls-surface-muted)]"}`} style={{ backgroundImage: "repeating-linear-gradient(to right,transparent 0,transparent calc(20% - 1px),#eae8e3 calc(20% - 1px),#eae8e3 20%)" }}>
            {data.events.filter(event => event.category === key).map(event => {
              const day = Math.max(0, Math.min(30, event.day));
              // Avoid overflowing the grid at the right edge; bars are display-only.
              const widthPercent = Math.max(12, ((event.duration ?? 4) / 30) * 100);
              const leftPercent = Math.min(day / 30 * 100, 100 - widthPercent);
              const isCurrent = event.id === selectedEvent;
              return <button key={event.id} type="button" title={`${event.title} · ${formatMoney(event.amount)} · ${event.source ?? "План"}`} aria-pressed={isCurrent} onClick={() => setSelectedEvent(isCurrent ? null : event.id)} style={{ left: `${leftPercent}%`, width: `${widthPercent}%` }} className={`absolute top-[7px] z-10 flex h-[30px] min-w-[104px] max-w-full cursor-pointer items-center gap-1.5 overflow-hidden rounded-[5px] border bg-[color:var(--puls-bg)] px-1.5 text-left text-[11px] text-[color:var(--puls-text)] shadow-[0_2px_4px_rgba(30,28,20,0.08)] transition-shadow hover:z-20 hover:shadow-md focus-visible:outline-2 focus-visible:outline-emerald-600 ${event.amount >= 0 ? "border-[color:var(--puls-border)] border-l-[3px] border-l-[color:var(--puls-chart-primary)]" : "border-[color:var(--puls-border)] border-l-[3px] border-l-[color:var(--puls-negative-text)]"} ${isCurrent ? "ring-2 ring-emerald-200" : ""}`}>
                <span className={`flex size-[18px] shrink-0 items-center justify-center rounded-full ${event.amount >= 0 ? "bg-[color:var(--puls-positive-bg)] text-[color:var(--puls-positive-text)]" : "bg-[color:var(--puls-negative-bg)] text-[color:var(--puls-negative-text)]"}`}>{event.amount >= 0 ? <ArrowDownRight size={13}/> : <ArrowUpRight size={13}/>}</span>
                <span className="truncate">{event.title}</span>
              </button>;
            })}
          </div>
        </div>)}
      </div>
    </div>
    {current ? <div className="mt-3 flex items-center gap-3 rounded-md border border-[color:var(--puls-border)] bg-[color:var(--puls-surface-soft)] px-3 py-2.5">
      <div className="mr-auto min-w-0"><p className="text-[12px] font-semibold text-[color:var(--puls-text)]">{current.title}</p><p className="mt-0.5 text-[11px] text-[color:var(--puls-text-muted)]">{displayDate(data.forecast[Math.max(0, Math.min(current.day, data.forecast.length - 1))].date)} · {current.source ?? "Плановое событие"}</p></div>
      <strong className={`shrink-0 text-[13px] ${current.amount >= 0 ? "text-[color:var(--puls-positive-text)]" : "text-[color:var(--puls-negative-text)]"}`}>{current.amount > 0 ? "+" : ""}{formatMoney(current.amount)}</strong>
      <button type="button" aria-label="Закрыть детали" onClick={() => setSelectedEvent(null)} className="shrink-0 cursor-pointer text-[color:var(--puls-text-muted)] hover:text-[color:var(--puls-text)]"><X size={17}/></button>
    </div> : <p className="mt-2.5 text-[11px] text-[color:var(--puls-text-faint)]">Нажми на событие, чтобы посмотреть сумму, дату и источник данных.</p>}
  </section>;
}

export function ScenarioComparison({ data, selected, onChangeScenario, onOpenScenarios }: {
  data: PulsOverviewData; selected: ScenarioKey; onChangeScenario: (key: ScenarioKey) => void; onOpenScenarios?: () => void;
}) {
  const stats = SCENARIOS.map(s => getForecastStats(data.forecast, s.key));
  const current = stats[SCENARIOS.findIndex(s => s.key === selected)]!;
  const cells = [
    { label: "Остаток через 30 дней", value: (s: typeof current) => formatMoney(s.last), delta: formatMoney(current.last - stats[0].last) },
    { label: "Минимальный остаток", value: (s: typeof current) => formatMoney(s.minimum), delta: formatMoney(current.minimum - stats[0].minimum) },
    { label: "Дней с дефицитом", value: (s: typeof current) => `${s.negativeDays} дн.`, delta: `${current.negativeDays - stats[0].negativeDays} дн.` },
    { label: "Максимальная нехватка", value: (s: typeof current) => formatMoney(s.deficit), delta: formatMoney(current.deficit - stats[0].deficit) },
    { label: "Первый кассовый разрыв", value: (s: typeof current) => s.firstNegative < 0 ? "Нет" : displayDate(data.forecast[s.firstNegative].date), delta: "—" },
  ];
  const colors: Record<ScenarioKey, string> = { base: "bg-[color:var(--puls-purple-bg)] text-[color:var(--puls-purple-text)]", delay: "bg-[color:var(--puls-good-bg)] text-[color:var(--puls-good-text)]", downturn: "bg-[color:var(--puls-demo-bg)] text-[color:var(--puls-demo-text)]" };
  return <section aria-label="Сравнение финансовых сценариев" className="mt-10 min-w-0">
    <header className="mb-4 flex items-start justify-between gap-3">
      <div><h2 className="text-[21px] font-semibold tracking-[-0.035em] text-[color:var(--puls-text)]">Сравнение сценариев</h2><p className="mt-0.5 text-[12px] text-[color:var(--puls-text-muted)]">Как изменения условий влияют на остаток денежных средств</p></div>
      <div className="flex shrink-0 items-center gap-2">
        <Button type="button" variant="outline" size="md" onClick={onOpenScenarios} disabled={!onOpenScenarios} className="bg-[color:var(--puls-purple-bg)]! text-[color:var(--puls-purple-text)]! [--button-outline-shadow:inset_0_0_0_1px_#d8b4ee] hover:bg-[color:var(--puls-purple-hover)]!"><Sparkles aria-hidden="true"/>Анализ</Button>
        <Button type="button" variant="outline" size="icon" aria-label="Открыть настройки сценариев" onClick={onOpenScenarios} disabled={!onOpenScenarios} className="text-[color:var(--puls-text-muted)]! [--button-outline-shadow:inset_0_0_0_1px_#e4e0db]"><SlidersHorizontal aria-hidden="true"/></Button>
      </div>
    </header>
    <div className="w-full overflow-x-auto border-t border-[color:var(--puls-border)]">
      <table className="w-full min-w-[790px] table-fixed border-separate border-spacing-0 text-[12px] text-[color:var(--puls-text-secondary)] tabular-nums">
        <thead><tr>
          <th className="w-[26%] border-r border-b border-[color:var(--puls-border-strong)] border-r-[#e4e0d9] px-2.5 py-2 text-left font-normal text-[color:var(--puls-text-muted)]">Показатель</th>
          {SCENARIOS.map(s => <th key={s.key} className="border-r border-b border-[color:var(--puls-border-strong)] border-r-[#e4e0d9] px-1.5 py-1.5 text-left font-normal">
            <button type="button" disabled={!scenarioSupported(data, s.key)} aria-pressed={selected === s.key} onClick={() => onChangeScenario(s.key)} className={`inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-[4px] border px-1.5 py-1 text-[12px] font-medium whitespace-nowrap text-[color:var(--puls-text-secondary)] hover:bg-[color:var(--puls-surface-active)] focus-visible:outline-2 focus-visible:outline-emerald-600 disabled:cursor-not-allowed disabled:opacity-35 ${selected === s.key ? "border-[color:var(--puls-border)] bg-[color:var(--puls-surface-active)]" : "border-transparent"}`}>
              <span className={`flex size-[17px] shrink-0 items-center justify-center rounded-[3px] ${colors[s.key]}`}><Activity size={13}/></span>{s.label}
            </button>
          </th>)}
          <th className="border-b border-[color:var(--puls-border-strong)] px-2.5 py-2 text-right font-normal text-[color:var(--puls-text-muted)]">Δ к базовому</th>
        </tr></thead>
        <tbody>{cells.map((row, rowIndex) => <tr key={row.label} className="odd:bg-[color:var(--puls-surface-muted)] hover:bg-[color:var(--puls-surface-active)]">
          <th scope="row" className={`h-[40px] border-r border-b border-r-[#b6b1a8] border-b-[#e3dfd9] px-3 text-left font-normal text-[color:var(--puls-text-secondary)] ${rowIndex === 0 ? "border-l-2 border-l-[color:var(--puls-text)]" : ""}`}>{row.label}{rowIndex === 1 && <span className="float-right text-[color:var(--puls-text-strong)]">✦</span>}</th>
          {SCENARIOS.map((scenario, index) => <td key={scenario.key} className={`h-[40px] border-r border-b border-r-[#e2dfd8] border-b-[#e3dfd9] px-2.5 text-right font-medium whitespace-nowrap ${selected === scenario.key ? "bg-[color:var(--puls-surface-active)]" : ""}`}>{scenarioSupported(data, scenario.key) ? row.value(stats[index]) : "—"}</td>)}
          <td className="h-[40px] border-b border-[color:var(--puls-border)] px-2.5 text-right whitespace-nowrap text-[color:var(--puls-text-secondary)]">{row.delta}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="mt-2.5 flex items-center gap-1.5 text-[11px] text-[color:var(--puls-text-faint)]"><CircleHelp size={14}/>Нажми на сценарий в таблице, чтобы переключить график.</p>
  </section>;
}

export function PulsEmptyState({ onAddSource }: { onAddSource?: () => void }) {
  return <section className="mt-5 flex min-h-[360px] flex-col items-center justify-center rounded-xl border border-dashed border-[color:var(--puls-border)] p-7 text-center">
    <div className="flex size-[58px] items-center justify-center rounded-xl bg-[color:var(--puls-good-bg)] text-[color:var(--puls-good-text)]"><Activity size={27}/></div>
    <h2 className="mt-4 text-[20px] font-semibold tracking-tight text-[color:var(--puls-text)]">Загрузите операции, чтобы увидеть прогноз</h2>
    <p className="mt-2 max-w-[440px] text-[13px] leading-relaxed text-[color:var(--puls-text-secondary)]">Здесь появятся финансовые показатели, прогноз на 30 дней, календарь платежей и сравнение сценариев.</p>
    {onAddSource && <button type="button" onClick={onAddSource} className="mt-4 inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-[#147d5c] px-3.5 py-2.5 text-[12px] font-semibold text-white hover:bg-[#106f52] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600"><Plus size={15}/>Добавить источник данных</button>}
  </section>;
}

export default function PulsOverview({ data = PULS_DEMO_DATA, onAddSource, onOpenForecast, onOpenCalendar, onOpenScenarios }: PulsOverviewProps) {
  const [requested, setRequested] = useState<ScenarioKey>("delay");
  const prepared = useMemo(() => data && data.forecast.length > 0 ? data : null, [data]);
  const selected = prepared && scenarioSupported(prepared, requested) ? requested : "base";
  return <div className="puls-overview min-w-0 w-full bg-[color:var(--puls-bg)] pb-10 text-[color:var(--puls-text)] tabular-nums">
    {prepared ? <>
      <div className="mb-3 flex min-h-[24px] flex-wrap items-center justify-end gap-3">
        {prepared.isDemo && <span className="inline-flex items-center gap-1.5 rounded-[5px] border border-[color:var(--puls-demo-border)] bg-[color:var(--puls-demo-bg)] px-2 py-0.5 text-[11px] text-[color:var(--puls-demo-text)]"><span className="size-1.5 rounded-full bg-[#d9a32a]"/>Демо-данные</span>}
        <span className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--puls-text-muted)]"><Clock3 size={13}/>{prepared.updatedAt ?? "Прогноз на 30 дней"}</span>
      </div>
      <KpiStrip data={prepared} selected={selected}/>
      <ForecastChart data={prepared} selected={selected} onChangeScenario={setRequested} onOpenForecast={onOpenForecast}/>
      <PaymentTimeline data={prepared} onOpenCalendar={onOpenCalendar}/>
      <ScenarioComparison data={prepared} selected={selected} onChangeScenario={setRequested} onOpenScenarios={onOpenScenarios}/>
      <p className="mt-6 text-[10px] leading-[18px] text-[color:var(--puls-text-faint)]">{prepared.isDemo ? "Синтетические демонстрационные данные. Числа не являются прогнозом реальной компании." : "Прогноз построен на загруженных данных; точность зависит от полноты информации и качества модели."}</p>
    </> : <PulsEmptyState onAddSource={onAddSource}/>}
  </div>;
}
