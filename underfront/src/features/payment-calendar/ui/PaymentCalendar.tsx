"use client";

import { CalendarDays } from "lucide-react";
import { Button } from "@/src/shared/ui/button";
import { Tabs } from "@/src/shared/ui/tabs";
import { PaymentBalanceChart } from "./PaymentBalanceChart";
import { PaymentEventCard } from "./PaymentEventCard";
import { PaymentMonthGrid } from "./PaymentMonthGrid";
import { PaymentTimeline } from "./PaymentTimeline";
import { addDays, dateKey, formatMoney, parseDate } from "@/src/entities/payment";
import type { MonthForecast, PaymentEvent, PaymentView } from "@/src/entities/payment";

export interface PaymentCalendarProps {
  month: Date;
  today: string;
  selectedDate: string;
  view: PaymentView;
  forecast: MonthForecast;
  onViewChange: (view: PaymentView) => void;
  onMonthChange: (monthOffset: number) => void;
  onToday: () => void;
  onSelectDate: (date: string) => void;
  onOpenEvent: (id: string) => void;
  onMoveEvent: (id: string, date: string) => void;
  onCreateEvent: () => void;
}

type AttentionItem = { event: PaymentEvent; date: string; reason: string; priority: number };

function attentionItems(forecast: MonthForecast, today: string): AttentionItem[] {
  const firstRisk = forecast.days.find((day) => day.date >= today && day.closing < 0 && day.opening >= 0);
  return forecast.days.flatMap((day) => day.events.flatMap((event): AttentionItem[] => {
    if (event.status === "cancelled" || event.status === "received") return [];
    if (event.direction === "income" && event.status === "overdue") return [{ event, date: day.date, reason: "Просрочено поступление", priority: 0 }];
    if (event.direction === "expense" && event.status === "overdue") return [{ event, date: day.date, reason: "Просрочен платёж", priority: 0 }];
    if (event.direction === "expense" && day.date === firstRisk?.date) return [{ event, date: day.date, reason: "День возможного разрыва", priority: 1 }];
    if (event.direction === "expense" && day.date >= today && day.date <= dateKey(addDays(parseDate(today), 7))) return [{ event, date: day.date, reason: "Скоро обязательный платёж", priority: 2 }];
    return [];
  })).sort((a, b) => a.priority - b.priority || a.date.localeCompare(b.date)).slice(0, 5);
}

export function PaymentCalendar({ month, today, selectedDate, view, forecast, onViewChange, onMonthChange, onToday, onSelectDate, onOpenEvent, onMoveEvent, onCreateEvent }: PaymentCalendarProps) {
  const monthLabel = month.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  const selectedDay = forecast.days.find((day) => day.date === selectedDate);
  const monthEventCount = forecast.days.reduce((count, day) => count + day.events.filter((event) => event.status !== "cancelled").length, 0);
  const firstDeficit = forecast.days.find((day) => day.date >= today && day.closing < 0);
  const isNewRisk = firstDeficit && firstDeficit.opening >= 0;
  const dayChange = selectedDay ? selectedDay.closing - selectedDay.opening : 0;
  const attention = attentionItems(forecast, today);
  const shared = { days: forecast.days, selectedDate, today, onSelectDate, onOpenEvent, onMoveEvent };

  return (
    <div className="w-full min-w-0 space-y-4 text-[13px] leading-5 text-[color:var(--nav-item-active-text)]">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[20px] font-semibold leading-6 tracking-tight text-[color:var(--text-primary)]">Платёжный календарь</h1>
          <p className="mt-1 text-[12px] leading-4 text-[color:var(--nav-item-text)]">Планирование денежных потоков по финансовым событиям</p>
        </div>
        <Button type="button" size="lg" onClick={onCreateEvent}>+ Событие</Button>
      </header>

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border-muted)] pb-3">
        <div className="flex items-center gap-1">
          <Button type="button" variant="outline" size="lg" aria-label="Предыдущий месяц" onClick={() => onMonthChange(-1)}>‹</Button>
          <span className="min-w-[146px] text-center text-[13px] font-semibold capitalize tabular-nums sm:min-w-[168px]">{monthLabel}</span>
          <Button type="button" variant="outline" size="lg" aria-label="Следующий месяц" onClick={() => onMonthChange(1)}>›</Button>
          <Button type="button" variant="outline" size="lg" className="ml-1" onClick={onToday}>Сегодня</Button>
        </div>
        <Tabs ariaLabel="Вид календаря" size="lg" value={view} onValueChange={(value) => onViewChange(value as PaymentView)} showContent={false} tabs={[{ key: "month", label: "День", content: null }, { key: "timeline", label: "План", content: null }]} />
      </div>

      {firstDeficit ? <div role="status" className="border-l-2 border-[color:var(--danger)] bg-[color:var(--sidebar-bg)] px-3 py-2 text-[12px] leading-4 transition-colors duration-300">
        <span className="font-semibold text-[color:var(--danger)]">{isNewRisk ? "Ближайший прогнозный разрыв:" : "Прогнозный дефицит продолжается:"}</span> {parseDate(firstDeficit.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })} · остаток <span className="font-semibold tabular-nums text-[color:var(--danger)]">{formatMoney(firstDeficit.closing)}</span>
      </div> : null}

      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
        <section className="min-w-0 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)] lg:sticky lg:top-16" aria-label="Выбор даты">
          <div className="flex min-h-12 items-center justify-between gap-2 border-b border-[color:var(--border-muted)] px-4 py-3">
            <h2 className="text-[16px] font-semibold leading-5 text-[color:var(--text-primary)]">Месяц</h2>
            <span className="text-[12px] text-[color:var(--nav-item-text)]">{monthEventCount} событий</span>
          </div>
          <div className="p-4"><PaymentMonthGrid {...shared} /></div>
        </section>

        <section className="min-w-0 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)]" aria-label={view === "month" ? "Выбранный день" : "План платежей"}>
          {view === "month" && selectedDay ? <>
            <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border-muted)] px-4 py-3">
              <div>
                <h2 className="text-[16px] font-semibold leading-5 text-[color:var(--text-primary)]">{parseDate(selectedDay.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", weekday: "long" })}</h2>
              </div>
              <span className={`inline-flex items-center gap-2 text-[12px] leading-5 ${selectedDay.closing < 0 ? "text-[color:var(--danger)]" : "text-[color:var(--nav-item-text)]"}`}><span className={`size-1.5 rounded-full ${selectedDay.closing < 0 ? "bg-[color:var(--danger)]" : "bg-[color:var(--accent)]"}`} />{selectedDay.closing < 0 ? "Возможная нехватка" : "Средств достаточно"}</span>
            </div>
            <div className="border-b border-[color:var(--border-muted)] px-4 py-3">
              <div>
                <p className="text-[12px] leading-4 text-[color:var(--nav-item-text)]">Прогнозный остаток на конец дня</p>
                <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <p className={`text-[20px] font-semibold leading-6 tracking-tight tabular-nums ${selectedDay.closing < 0 ? "text-[color:var(--danger)]" : "text-[color:var(--text-primary)]"}`}>{formatMoney(selectedDay.closing)}</p>
                  <span className={`text-[12px] leading-4 tabular-nums ${dayChange > 0 ? "text-[color:var(--accent)]" : "text-[color:var(--nav-item-text)]"}`}>{dayChange === 0 ? "Без изменений к предыдущему дню" : `${dayChange > 0 ? "+" : "−"}${formatMoney(Math.abs(dayChange))} к предыдущему дню`}</span>
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 border-b border-[color:var(--border-muted)] px-4 py-3 text-[12px] leading-4">
              <div><p className="text-[color:var(--nav-item-text)]">Поступления</p><p className="mt-1 text-[15px] font-semibold leading-5 tabular-nums text-[color:var(--accent)]">{selectedDay.income ? "+" : ""}{formatMoney(selectedDay.income)}</p></div>
              <div><p className="text-[color:var(--nav-item-text)]">Списания</p><p className="mt-1 text-[15px] font-semibold leading-5 tabular-nums text-[color:var(--nav-item-active-text)]">{selectedDay.expense ? "−" : ""}{formatMoney(selectedDay.expense)}</p></div>
            </div>
            <div className="px-2 py-2">
              <div className="flex items-center justify-between gap-2 px-2 pb-1"><h3 className="text-[15px] font-semibold leading-5">События дня</h3><span className="text-[12px] text-[color:var(--nav-item-text)]">{selectedDay.events.length ? `${selectedDay.events.length} · перетащите на дату слева` : "0 событий"}</span></div>
              {selectedDay.events.length ? <div className="divide-y divide-[color:var(--border-muted)]">{selectedDay.events.map((event) => <PaymentEventCard key={event.id} event={event} onOpen={onOpenEvent} />)}</div> : <div className="flex items-center gap-3 px-2 py-2">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-[4px] bg-[color:var(--sidebar-bg)] text-[color:var(--nav-item-icon)]"><CalendarDays size={15} strokeWidth={1.7} aria-hidden="true" /></span>
                <p className="min-w-0 flex-1 text-[12px] leading-4 text-[color:var(--nav-item-text)]">На этот день платежей нет</p><Button type="button" variant="outline" size="md" onClick={onCreateEvent}>Добавить</Button>
              </div>}
            </div>
          </> : <PaymentTimeline {...shared} />}
        </section>
      </div>

      <div className="grid min-w-0 items-start gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.9fr)]">
        <section className="min-w-0 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)]" aria-label="Требует внимания">
          <div className="flex min-h-[52px] flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border-muted)] px-4 py-3"><h2 className="text-[16px] font-semibold leading-5 text-[color:var(--text-primary)]">Требует внимания</h2><span className="text-[12px] text-[color:var(--nav-item-text)]">{attention.length ? `${attention.length} событий` : "Всё спокойно"}</span></div>
          {attention.length ? <div className="divide-y divide-[color:var(--border-muted)] px-2 py-1">
            {attention.map(({ date, event, reason }) => <div key={event.id} className="flex min-w-0 items-center gap-2">
              <button type="button" onClick={() => onSelectDate(date)} className="w-14 shrink-0 rounded-[4px] text-center text-[12px] tabular-nums text-[color:var(--nav-item-text)] hover:text-[color:var(--nav-item-active-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)]">{parseDate(date).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</button>
              <div className="min-w-0 flex-1 py-1"><span className={`block px-2 text-[11px] leading-4 ${reason === "День возможного разрыва" ? "text-[color:var(--danger)]" : reason.startsWith("Просроч") ? "text-[color:var(--warning)]" : "text-[color:var(--nav-item-text)]"}`}>{reason}</span><PaymentEventCard event={event} onOpen={onOpenEvent} compact /></div>
            </div>)}
          </div> : <p className="px-4 py-4 text-[12px] text-[color:var(--nav-item-text)]">Просроченных и ближайших обязательных платежей нет.</p>}
        </section>

        <section className="min-w-0 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)]" aria-label="Динамика остатка">
          <div className="flex min-h-[52px] flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border-muted)] px-4 py-3"><h2 className="text-[16px] font-semibold leading-5 text-[color:var(--text-primary)]">Динамика остатка</h2><span className="text-[12px] tabular-nums text-[color:var(--nav-item-text)]">{formatMoney(forecast.opening)} → {formatMoney(forecast.closing)}</span></div>
          <div className="px-3 pt-2"><PaymentBalanceChart days={forecast.days} selectedDate={selectedDate} /></div>
          <p className="px-4 pb-3 text-[12px] leading-4 text-[color:var(--nav-item-text)]">Демо-расчёт: просроченные поступления и отменённые события не учитываются.</p>
        </section>
      </div>
    </div>
  );
}
