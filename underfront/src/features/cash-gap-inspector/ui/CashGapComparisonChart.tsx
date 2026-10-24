"use client";

import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatGapDate, type GapForecast } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";

type ComparisonPoint = { index: number; date: string; before: number; after: number | null };

function ComparisonTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: ComparisonPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return <div className="rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-3 text-[12px] leading-5 text-[color:var(--nav-item-active-text)]">
    <p className="font-medium">{formatGapDate(point.date, true)}</p>
    <p className="tabular-nums">До: {formatRub(point.before)}</p>
    <p className="tabular-nums text-[color:var(--accent)]">После: {point.after === null ? "Нет данных" : formatRub(point.after)}</p>
  </div>;
}

export function CashGapComparisonChart({ baseline, alternative }: { baseline: GapForecast; alternative: GapForecast }) {
  const alternatives = new Map(alternative.days.map((day) => [day.date, day.closing]));
  const data: ComparisonPoint[] = baseline.days.map((day, index) => ({ index, date: day.date, before: day.closing, after: alternatives.get(day.date) ?? null }));
  const periods: Array<{ from: number; to: number }> = [];
  data.forEach((point, index) => {
    if (point.before >= 0 && (point.after === null || point.after >= 0)) return;
    const last = periods[periods.length - 1];
    if (last && last.to === index - 1) last.to = index;
    else periods.push({ from: index, to: index });
  });
  return <div className="h-[220px] min-w-0 w-full" role="img" aria-label="Прогноз остатка до и после выбранных действий; затенены дни нехватки">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: 0 }} accessibilityLayer>
        <CartesianGrid vertical={false} stroke="var(--border-muted)" strokeDasharray="2 4" />
        <XAxis dataKey="index" type="number" domain={[0, Math.max(1, data.length - 1)]} allowDecimals={false} tickCount={7} tickFormatter={(index: number) => data[index] ? formatGapDate(data[index].date) : ""} tick={{ fill: "var(--nav-item-text)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--border)" }} />
        <YAxis width={58} tickCount={5} domain={[(min: number) => Math.min(min, 0), (max: number) => Math.max(max, 0)]} tickFormatter={(value: number) => `${Math.round(value / 1000)} тыс.`} tick={{ fill: "var(--nav-item-text)", fontSize: 11 }} tickLine={false} axisLine={false} />
        {periods.map((period) => <ReferenceArea key={period.from} x1={Math.max(0, period.from - 0.4)} x2={Math.min(data.length - 1, period.to + 0.4)} fill="var(--danger)" fillOpacity={0.06} strokeOpacity={0} />)}
        <ReferenceLine y={0} stroke="var(--nav-item-icon)" strokeDasharray="3 3" />
        <Tooltip content={<ComparisonTooltip />} cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }} />
        <Line dataKey="before" name="До" type="linear" stroke="var(--nav-item-icon)" strokeDasharray="4 3" strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} isAnimationActive={false} />
        <Line dataKey="after" name="После" type="linear" stroke="var(--accent)" strokeWidth={2} dot={false} activeDot={{ r: 3 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>;
}
