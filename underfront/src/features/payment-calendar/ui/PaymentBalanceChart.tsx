"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCompactMoney, formatMoney, parseDate } from "@/src/entities/payment";
import type { DailyBalance } from "@/src/entities/payment";

type ChartPoint = { date: string; label: string; balance: number; change: number; events: DailyBalance["events"] };

function BalanceTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: ChartPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  const change = point.change;
  return (
    <div className="rounded-[4px] border border-[color:var(--border)] bg-[color:var(--surface-elevated)] px-3 py-2 text-[12px] leading-4 text-[color:var(--nav-item-active-text)]">
      <p className="font-medium">{parseDate(point.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "short" })}</p>
      <p className={`mt-1 font-semibold tabular-nums ${point.balance < 0 ? "text-[color:var(--danger)]" : ""}`}>Остаток {formatMoney(point.balance)}</p>
      <p className="mt-1 tabular-nums text-[color:var(--nav-item-text)]">За день {change > 0 ? "+" : change < 0 ? "−" : ""}{formatMoney(Math.abs(change))}</p>
      <div className="mt-2 border-t border-[color:var(--border-muted)] pt-1.5">
        {point.events.length ? point.events.map((event) => <p key={event.id} className={`flex max-w-[260px] justify-between gap-3 leading-5 ${event.status === "cancelled" ? "text-[color:var(--nav-item-text)] line-through" : ""}`}><span className="truncate">{event.title}{event.direction === "income" && event.status === "overdue" ? " · не учтено" : ""}</span><span className="shrink-0 tabular-nums">{event.direction === "income" ? "+" : "−"}{formatCompactMoney(event.amount)} ₽</span></p>) : <p className="text-[color:var(--nav-item-text)]">Событий нет</p>}
      </div>
    </div>
  );
}

export function PaymentBalanceChart({ days, selectedDate }: { days: DailyBalance[]; selectedDate?: string }) {
  const data: ChartPoint[] = useMemo(() => days.map((day) => ({ date: day.date, label: String(parseDate(day.date).getDate()), balance: day.closing, change: day.closing - day.opening, events: day.events })), [days]);
  const hasShortfall = days.some((day) => day.closing < 0);
  const selectedIndex = days.findIndex((day) => day.date === selectedDate);
  return (
    <div className="h-[172px] w-full min-w-0 pt-2" role="img" aria-label="График прогнозного остатка по дням месяца">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="var(--border-muted)" strokeDasharray="2 4" vertical={false} />
          <XAxis dataKey="label" tick={{ fill: "var(--nav-item-text)", fontSize: 11 }} axisLine={{ stroke: "var(--border)" }} tickLine={false} interval={4} />
          <YAxis width={52} tick={{ fill: "var(--nav-item-text)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(value: number) => formatCompactMoney(value)} domain={[(minimum: number) => Math.min(minimum, 0), (maximum: number) => Math.max(maximum, 0)]} />
          <Tooltip key={selectedDate} content={<BalanceTooltip />} defaultIndex={selectedIndex >= 0 ? selectedIndex : undefined} cursor={{ stroke: "var(--border-strong)", strokeDasharray: "2 3" }} />
          <ReferenceLine y={0} stroke={hasShortfall ? "var(--danger)" : "var(--nav-item-text)"} strokeDasharray="3 4" strokeOpacity={0.75} />
          {selectedIndex >= 0 ? <ReferenceLine x={data[selectedIndex].label} stroke="var(--accent)" strokeDasharray="3 3" strokeOpacity={0.85} /> : null}
          <Line type="linear" dataKey="balance" name="Остаток" stroke="var(--nav-item-active-text)" strokeWidth={1.8} dot={false} activeDot={{ r: 3, fill: "var(--accent)", stroke: "var(--surface)", strokeWidth: 1 }} isAnimationActive animationDuration={280} animationEasing="ease-out" />
          {selectedIndex >= 0 ? <ReferenceDot x={data[selectedIndex].label} y={data[selectedIndex].balance} r={3.5} fill="var(--accent)" stroke="var(--surface)" strokeWidth={1.5} /> : null}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
