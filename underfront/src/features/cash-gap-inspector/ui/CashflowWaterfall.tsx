"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { WaterfallStep } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";

type WaterfallPoint = WaterfallStep & { range: [number, number]; formatted: string };

function WaterfallTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: WaterfallPoint }> }) {
  const step = payload?.[0]?.payload;
  if (!active || !step) return null;
  return <div className="max-w-[260px] rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-3 text-[12px] leading-5 text-[color:var(--nav-item-active-text)]">
    <p className="font-medium">{step.title}</p><p className="tabular-nums">Сумма: {step.formatted}</p>
    <p className="tabular-nums">Остаток: {formatRub(step.after)}</p>
    {step.event ? <p className="text-[color:var(--nav-item-text)]">{step.event.counterparty}</p> : null}
  </div>;
}

export function CashflowWaterfall({ steps }: { steps: readonly WaterfallStep[] }) {
  const data: WaterfallPoint[] = steps.map((step) => ({ ...step, range: [Math.min(step.before, step.after), Math.max(step.before, step.after)], formatted: `${step.kind === "income" ? "+" : ""}${formatRub(step.amount)}` }));
  return <div className="min-w-0 w-full" style={{ height: Math.max(230, steps.length * 34) }} role="img" aria-label="Каскад изменения денег: начальный остаток, поступления, списания и итог">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 86, left: 0, bottom: 0 }} barSize={14} accessibilityLayer>
        <CartesianGrid horizontal={false} stroke="var(--border-muted)" strokeDasharray="2 4" />
        <XAxis type="number" domain={[(min: number) => Math.min(0, min), (max: number) => Math.max(0, max)]} tick={{ fill: "var(--nav-item-text)", fontSize: 11 }} tickFormatter={(value: number) => `${Math.round(value / 1000)} тыс.`} tickLine={false} axisLine={false} tickCount={4} />
        <YAxis dataKey="title" type="category" width={116} tickFormatter={(title: string) => title.length > 19 ? `${title.slice(0, 18)}…` : title} tick={{ fill: "var(--nav-item-active-text)", fontSize: 11 }} tickLine={false} axisLine={false} />
        <ReferenceLine x={0} stroke="var(--nav-item-icon)" strokeDasharray="3 3" />
        <Tooltip content={<WaterfallTooltip />} cursor={{ fill: "var(--nav-item-hover-bg)", fillOpacity: 0.6 }} />
        <Bar dataKey="range" isAnimationActive={false} radius={2}>
          {data.map((step) => <Cell key={step.id} fill={step.kind === "closing" && step.after < 0 ? "var(--danger)" : step.kind === "income" ? "var(--accent)" : "var(--nav-item-active-text)"} fillOpacity={step.kind === "expense" ? 0.65 : 0.9} />)}
          <LabelList dataKey="formatted" position="right" fill="var(--nav-item-active-text)" fontSize={11} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  </div>;
}
