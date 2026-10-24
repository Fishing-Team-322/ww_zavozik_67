"use client";

import { useId } from "react";
import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

/** An intentionally dumb visualization: amounts and risk boundaries MUST come from your model/API. */
export type CashflowDay = {
  date: string;
  actual?: number | null;
  baseline?: number | null;
  scenario?: number | null;
  lowerBound?: number | null;
  upperBound?: number | null;
  events?: string[];
};

export type CashflowForecastChartProps = {
  days: CashflowDay[];
  height?: number;
  currency?: string;
  showScenario?: boolean;
  showBounds?: boolean;
  onDayClick?: (date: string) => void;
  compactDates?: boolean;
  scenarioLabel?: string;
  hideSeries?: boolean;
  animate?: boolean;
  showDeficitDots?: boolean;
  firstGapDate?: string;
  showScenarioDelta?: boolean;
};

function amount(value: number, currency: string) {
  return `${Math.round(value).toLocaleString("ru-RU")} ${currency}`;
}

const shortDate = (date: string) => new Date(`${date.slice(0, 10)}T00:00:00Z`).toLocaleDateString("ru-RU", { day: "numeric", month: "short", timeZone: "UTC" });

export function CashflowForecastChart({days, height = 330, currency = "₽", showScenario = true, showBounds = false, onDayClick, compactDates = false, scenarioLabel = "Негативный сценарий", hideSeries = false, animate = true, showDeficitDots = true, firstGapDate, showScenarioDelta = false}: CashflowForecastChartProps) {
  const uid = useId().replace(/:/g, "");
  const deficitPeriods: Array<{start: string; end: string; minimum: number}> = [];
  const deficitPoints: Array<{date: string; value: number}> = [];
  for (let index = 0; index < days.length; index++) {
    const values = [days[index].baseline, showScenario ? days[index].scenario : null].filter((value): value is number => value != null);
    const minimum = Math.min(0, ...values);
    if (minimum >= 0) continue;
    deficitPoints.push({date: days[index].date, value: minimum});
    const previous = deficitPeriods.at(-1);
    if (index > 0 && previous?.end === days[index - 1].date) {
      previous.end = days[index].date;
      previous.minimum = Math.min(previous.minimum, minimum);
    } else {
      deficitPeriods.push({start: days[index].date, end: days[index].date, minimum});
    }
  }
  if (!days.length) {
    return <div style={{height}} className="flex items-center justify-center rounded-xl bg-[color:var(--surface-subtle)] text-sm text-[color:var(--text-secondary)]">Прогноз пока недоступен. Загрузите данные.</div>;
  }
  return (
    <div className="min-w-0 w-full" style={{height, cursor: onDayClick ? "pointer" : undefined}} role="img" aria-label="График ежедневного остатка средств с нулевой линией и сравнением сценариев">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <ComposedChart data={days} margin={{top:20, right:16, bottom:8, left:2}} onClick={state => {
          const date = state?.activePayload?.map(item => item.payload).find(point => point && days.some(day => day.date === point.date))?.date ?? state?.activeLabel;
          if (typeof date === "string" && days.some(day => day.date === date)) onDayClick?.(date);
        }}>
          <defs>
            <linearGradient id={`pulsCashflow-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.18}/>
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.015}/>
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 6" vertical={false} stroke="var(--divider)"/>
          <XAxis dataKey="date" minTickGap={18} tickLine={false} axisLine={false} tick={{fontSize:11, fill:"var(--text-secondary)"}} tickFormatter={compactDates ? shortDate : undefined}/>
          <YAxis tickLine={false} axisLine={false} width={56} tick={{fontSize:11, fill:"var(--text-secondary)"}} tickFormatter={(value:number)=>Math.abs(value)>=1000000?`${(value/1000000).toFixed(1)}м`:Math.abs(value)>=10000?`${Math.round(value/1000)}к`:Math.abs(value)>=1000?`${(value/1000).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}к`:`${Math.round(value).toLocaleString("ru-RU")}`}/>
          <ReferenceLine y={0} stroke="var(--danger)" strokeWidth={1.5} strokeDasharray="5 4" label={{value:"0 ₽", position:"insideTopRight", fill:"var(--danger)", fontSize:11}}/>
          {!hideSeries && firstGapDate && days.some(day => day.date === firstGapDate) && <ReferenceLine x={firstGapDate} stroke="var(--danger)" strokeDasharray="3 4" label={{value:"Первая нехватка", position:"insideTopLeft", fill:"var(--danger)", fontSize:11}} />}
          {!hideSeries && deficitPeriods.map((period) => <ReferenceArea key={`period-${period.start}`} x1={period.start} x2={period.end} y1={period.minimum} y2={0} fill="var(--danger)" fillOpacity={0.12} strokeOpacity={0} />)}
          {!hideSeries && showDeficitDots && deficitPoints.map((point) => <ReferenceDot key={`point-${point.date}`} x={point.date} y={point.value} r={5} fill="var(--danger)" stroke="var(--surface)" strokeWidth={2} />)}
          {!hideSeries && <Tooltip content={({active,payload,label})=>active && payload?.length ? (
            <div className="rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-3 shadow-[var(--shadow-md)]">
              <div className="mb-2 text-xs font-semibold text-[color:var(--text-primary)]">{compactDates && typeof label === "string" ? shortDate(label) : label}</div>
              {payload.filter(p=>p.value!=null).map((entry,index)=>(
                <div key={`${String(entry.dataKey)}-${index}`} className="flex items-center justify-between gap-5 py-0.5 text-xs">
                  <span className="flex items-center gap-2 text-[color:var(--text-secondary)]"><i className="h-2 w-2 rounded-full" style={{background: String(entry.color ?? 'var(--accent)')}}/>{entry.name}</span>
                  <span className="font-semibold text-[color:var(--text-primary)] tabular-nums">{amount(Number(entry.value),currency)}</span>
                </div>
              ))}
              {showScenarioDelta && (() => {
                const day = days.find(item => item.date === label);
                if (day?.baseline == null || day.scenario == null) return null;
                const difference = day.scenario - day.baseline;
                return <div className="mt-1 flex items-center justify-between gap-5 border-t border-[color:var(--border)] pt-1 text-xs"><span className="text-[color:var(--text-secondary)]">Разница</span><span className={`font-semibold tabular-nums ${difference < 0 ? "text-[color:var(--danger)]" : difference > 0 ? "text-[color:var(--success)]" : "text-[color:var(--text-primary)]"}`}>{difference > 0 ? "+" : ""}{amount(difference, currency)}</span></div>;
              })()}
              {days.find((day) => day.date === label)?.events?.map((event, index) => <p key={index} className="mt-2 max-w-64 text-xs leading-4 text-[color:var(--text-secondary)]">{event}</p>)}
            </div>
          ):null}/>}
          {!hideSeries && showBounds ? <Area dataKey="upperBound" name="Верхняя граница" type="monotone" stroke="var(--text-muted)" fill="none" strokeDasharray="2 4" dot={false} connectNulls={false} strokeWidth={1} isAnimationActive={animate}/> : null}
          {!hideSeries && showBounds ? <Area dataKey="lowerBound" name="Нижняя граница" type="monotone" stroke="var(--text-muted)" fill="none" strokeDasharray="2 4" dot={false} connectNulls={false} strokeWidth={1} isAnimationActive={animate}/> : null}
          {hideSeries && <Area dataKey="baseline" type="monotone" stroke="none" fill="none" dot={false} isAnimationActive={false} />}
          {!hideSeries && <Area dataKey="baseline" name="Базовый прогноз" stroke="var(--accent)" strokeWidth={2.5} fill={`url(#pulsCashflow-${uid})`} dot={false} type="monotone" connectNulls={false} isAnimationActive={animate}/>}
          {!hideSeries && <Line dataKey="actual" name="История / факт" stroke="var(--chart-series-primary)" strokeWidth={2.5} dot={false} type="monotone" connectNulls={false} isAnimationActive={animate}/>}
          {!hideSeries && showScenario ? <Line dataKey="scenario" name={scenarioLabel} stroke="var(--warning)" strokeWidth={2.5} strokeDasharray="5 4" dot={false} type="monotone" connectNulls={false} isAnimationActive={animate}/> : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
