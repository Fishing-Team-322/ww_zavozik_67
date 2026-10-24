"use client";

import { useEffect, useState } from "react";
import { Button } from "@/src/shared/ui/button";
import { formatMoney, parseDate } from "@/src/entities/payment";
import { PaymentEventCard } from "./PaymentEventCard";
import type { DailyBalance } from "@/src/entities/payment";

interface PaymentTimelineProps {
  days: DailyBalance[];
  selectedDate: string;
  today: string;
  onSelectDate: (date: string) => void;
  onOpenEvent: (id: string) => void;
  onMoveEvent: (id: string, date: string) => void;
}

const PERIOD_LENGTH = 7;

export function PaymentTimeline({ days, selectedDate, today, onSelectDate, onOpenEvent, onMoveEvent }: PaymentTimelineProps) {
  const lastStart = Math.max(0, days.length - PERIOD_LENGTH);
  const [startIndex, setStartIndex] = useState(() => {
    const index = Math.max(0, days.findIndex((day) => day.date === selectedDate));
    return Math.min(Math.floor(index / PERIOD_LENGTH) * PERIOD_LENGTH, lastStart);
  });

  useEffect(() => {
    const index = days.findIndex((day) => day.date === selectedDate);
    if (index < 0) return;
    setStartIndex((current) => index >= current && index < current + PERIOD_LENGTH
      ? current
      : Math.min(Math.floor(index / PERIOD_LENGTH) * PERIOD_LENGTH, lastStart));
  }, [days, selectedDate, lastStart]);

  const visibleDays = days.slice(startIndex, startIndex + PERIOD_LENGTH);
  const periodLabel = visibleDays.length
    ? `${parseDate(visibleDays[0].date).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })} — ${parseDate(visibleDays[visibleDays.length - 1].date).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}`
    : "";

  function changePeriod(offset: number) {
    const next = Math.max(0, Math.min(lastStart, startIndex + offset * PERIOD_LENGTH));
    setStartIndex(next);
    if (days[next]) onSelectDate(days[next].date);
  }

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border-muted)] px-4 py-3">
        <div><h2 className="text-[16px] font-semibold leading-5 text-[color:var(--text-primary)]">План платежей</h2><p className="mt-1 text-[12px] leading-4 text-[color:var(--nav-item-text)]">События можно переносить между днями</p></div>
        <div className="flex items-center gap-1">
          <Button type="button" size="md" variant="outline" aria-label="Предыдущие 7 дней" disabled={startIndex === 0} onClick={() => changePeriod(-1)}>‹</Button>
          <span className="min-w-[126px] text-center text-[12px] font-medium tabular-nums">{periodLabel}</span>
          <Button type="button" size="md" variant="outline" aria-label="Следующие 7 дней" disabled={startIndex >= lastStart} onClick={() => changePeriod(1)}>›</Button>
        </div>
      </div>
      <div>
        {visibleDays.map((day) => {
          const selected = day.date === selectedDate;
          const risk = day.closing < 0;
          const hasEvents = day.events.some((event) => event.status !== "cancelled");
          return <section
            key={day.date}
            onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "move"; }}
            onDrop={(event) => { event.preventDefault(); const id = event.dataTransfer.getData("text/plain"); if (id) onMoveEvent(id, day.date); }}
            className={`grid grid-cols-[104px_minmax(0,1fr)] border-b border-[color:var(--border-muted)] last:border-b-0 sm:grid-cols-[136px_minmax(0,1fr)] ${selected ? "bg-[color:var(--sidebar-bg)]" : "hover:bg-[color:var(--nav-item-hover-bg)]"} ${hasEvents ? "min-h-12" : "min-h-7"} transition-colors`}
          >
            <button type="button" onClick={() => onSelectDate(day.date)} className={`relative min-w-0 border-r border-[color:var(--border)] px-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)] ${hasEvents ? "py-2" : "py-1"}`}>
              <span aria-hidden="true" className={`absolute -right-[4px] top-3 z-10 size-2 rounded-full border-2 border-[color:var(--surface)] ${risk ? "bg-[color:var(--danger)]" : selected || day.date === today ? "bg-[color:var(--nav-item-active-text)]" : hasEvents ? "bg-[color:var(--nav-item-icon)]" : "bg-[color:var(--border)]"}`} />
              <span className={`block text-[12px] leading-4 ${hasEvents || selected ? "font-semibold text-[color:var(--nav-item-active-text)]" : "font-medium text-[color:var(--nav-item-text)]"}`}>{parseDate(day.date).toLocaleDateString("ru-RU", { day: "numeric", weekday: "short" })}{day.date === today ? " · сегодня" : ""}</span>
              {hasEvents || risk ? <span className={`block truncate text-[12px] leading-4 tabular-nums ${risk ? "font-semibold text-[color:var(--danger)]" : "text-[color:var(--nav-item-text)]"}`} title={formatMoney(day.closing)}>{formatMoney(day.closing)}</span> : null}
            </button>
            <div className={`min-w-0 px-2 ${hasEvents ? "py-1" : "py-0"}`} title={day.events.length ? undefined : "Нет платежей — перетащите сюда событие"}>
              {day.events.length ? <div className="divide-y divide-[color:var(--border-muted)]">{day.events.map((event) => <PaymentEventCard key={event.id} event={event} onOpen={onOpenEvent} compact />)}</div> : <span className="sr-only">Нет платежей — сюда можно перенести событие</span>}
            </div>
          </section>;
        })}
      </div>
    </div>
  );
}
