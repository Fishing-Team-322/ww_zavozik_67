"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/src/shared/ui/button";
import { Dialog } from "@/src/shared/ui/dialog";
import { Tabs } from "@/src/shared/ui/tabs";
import { PaymentCalendar } from "./PaymentCalendar";
import { PaymentEventForm } from "./PaymentEventForm";
import { PaymentEventPanel } from "./PaymentEventPanel";
import { addMonths, calculateMonthForecast, dateKey, formatMoney, monthStart, parseDate } from "@/src/entities/payment";
import { DEMO_OPENING_BALANCE, createMockPayments } from "../model/mock-data";
import { parseMockPayment } from "../model/mock-parser";
import type { PaymentDraft, PaymentEvent, PaymentView } from "@/src/entities/payment";

type Notice = { text: string; undo?: { id: string; oldDate: string } };

function emptyDraft(date: string): PaymentDraft {
  return { title: "", counterparty: "", amount: 0, date, direction: "expense", category: "Прочее", status: "expected" };
}

function draftFromEvent(event: PaymentEvent): PaymentDraft {
  return { title: event.title, counterparty: event.counterparty, amount: event.amount, date: event.date, direction: event.direction, category: event.category, probability: event.probability, status: event.status };
}

export function PaymentCalendarDemo() {
  const [today] = useState(() => new Date());
  const [anchorMonth] = useState(() => monthStart(today));
  const [month, setMonth] = useState(() => monthStart(today));
  const [selectedDate, setSelectedDate] = useState(() => dateKey(today));
  const [view, setView] = useState<PaymentView>("month");
  const [events, setEvents] = useState<PaymentEvent[]>(() => createMockPayments(today));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PaymentDraft>(() => emptyDraft(dateKey(today)));
  const [createOpen, setCreateOpen] = useState(false);
  const [createMode, setCreateMode] = useState<"manual" | "natural">("manual");
  const [naturalText, setNaturalText] = useState("");
  const [parsed, setParsed] = useState(false);
  const [parseError, setParseError] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const todayKey = dateKey(today);
  const forecast = useMemo(() => calculateMonthForecast(month, anchorMonth, DEMO_OPENING_BALANCE, events), [month, anchorMonth, events]);
  const selectedEvent = events.find((event) => event.id === selectedId) ?? null;

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 9000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  function openEvent(id: string) {
    const event = events.find((item) => item.id === id);
    if (!event) return;
    setSelectedId(id);
    setSelectedDate(event.date);
    setDraft(draftFromEvent(event));
    setEditing(false);
  }

  function moveEvent(id: string, date: string) {
    const event = events.find((item) => item.id === id);
    if (!event || event.date === date) return;
    setEvents((current) => current.map((item) => item.id === id ? { ...item, date } : item));
    setSelectedDate(date);
    setNotice({ text: `«${event.title}» перенесено на ${parseDate(date).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}. Остатки пересчитаны локально.`, undo: { id, oldDate: event.date } });
  }

  function openCreate() {
    setDraft(emptyDraft(selectedDate));
    setNaturalText("");
    setParsed(false);
    setParseError(false);
    setCreateMode("manual");
    setCreateOpen(true);
  }

  function createEvent() {
    if (!draft.title.trim() || !draft.counterparty.trim() || !draft.date || !Number.isFinite(draft.amount) || draft.amount <= 0) return;
    const next: PaymentEvent = { ...draft, id: `manual-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`, title: draft.title.trim(), counterparty: draft.counterparty.trim(), source: "Вручную", manual: true, probability: draft.direction === "income" ? draft.probability : undefined };
    setEvents((current) => [...current, next]);
    setMonth(monthStart(parseDate(next.date)));
    setSelectedDate(next.date);
    setCreateOpen(false);
    setNotice({ text: `Событие «${next.title}» добавлено. Остатки пересчитаны локально.` });
  }

  function saveEvent() {
    if (!selectedEvent || !draft.title.trim() || !draft.counterparty.trim() || !draft.date || !Number.isFinite(draft.amount) || draft.amount <= 0) return;
    setEvents((current) => current.map((item) => item.id === selectedEvent.id ? { ...item, ...draft, title: draft.title.trim(), counterparty: draft.counterparty.trim(), probability: draft.direction === "income" ? draft.probability : undefined } : item));
    setMonth(monthStart(parseDate(draft.date)));
    setSelectedDate(draft.date);
    setEditing(false);
    setNotice({ text: `Событие «${draft.title.trim()}» обновлено. Остатки пересчитаны локально.` });
  }

  function deleteEvent() {
    if (!selectedEvent?.manual) return;
    setEvents((current) => current.filter((item) => item.id !== selectedEvent.id));
    setSelectedId(null);
    setNotice({ text: `Событие «${selectedEvent.title}» удалено. Остатки пересчитаны локально.` });
  }

  function parseNatural() {
    const result = parseMockPayment(naturalText, today);
    if (!result) { setParsed(false); setParseError(true); return; }
    setDraft(result);
    setParsed(true);
    setParseError(false);
  }

  return (
    <>
      <PaymentCalendar
        month={month}
        today={todayKey}
        selectedDate={selectedDate}
        view={view}
        forecast={forecast}
        onViewChange={setView}
        onMonthChange={(offset) => { const next = addMonths(month, offset); setMonth(next); setSelectedDate(dateKey(next)); }}
        onToday={() => { setMonth(monthStart(today)); setSelectedDate(todayKey); }}
        onSelectDate={setSelectedDate}
        onOpenEvent={openEvent}
        onMoveEvent={moveEvent}
        onCreateEvent={openCreate}
      />
      <PaymentEventPanel
        event={selectedEvent}
        editing={editing}
        draft={draft}
        onDraftChange={setDraft}
        onClose={() => { setSelectedId(null); setEditing(false); }}
        onEdit={() => setEditing(true)}
        onCancelEdit={() => { if (selectedEvent) setDraft(draftFromEvent(selectedEvent)); setEditing(false); }}
        onSave={saveEvent}
        onDelete={deleteEvent}
      />
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="Новое событие" description="Добавьте платёж вручную или опишите его одной фразой." className="max-w-[490px] !shadow-none">
        <Tabs
          ariaLabel="Способ добавления события"
          value={createMode}
          onValueChange={(value) => setCreateMode(value as "manual" | "natural")}
          showContent={false}
          tabs={[{ key: "manual", label: "Вручную", content: null }, { key: "natural", label: "Текстом", content: null }]}
          className="mb-4"
        />
        {createMode === "manual" ? <PaymentEventForm draft={draft} onChange={setDraft} onSubmit={createEvent} submitLabel="Добавить событие" onCancel={() => setCreateOpen(false)} /> : <div className="space-y-3">
          <label htmlFor="payment-natural-input" className="block text-xs font-medium">Опишите платёж</label>
          <textarea id="payment-natural-input" rows={3} value={naturalText} onChange={(event) => { setNaturalText(event.target.value); setDraft(emptyDraft(selectedDate)); setParsed(false); setParseError(false); }} placeholder="Клиент Альфа заплатит 300 000 рублей 20 ноября" className="w-full resize-y rounded-[5px] border border-[color:var(--input-border)] bg-[color:var(--input-background)] px-3 py-2 text-sm text-[color:var(--input-text)] outline-none placeholder:text-[color:var(--input-placeholder)] focus:border-[color:var(--input-border-focus)]" />
          <p className="text-[11px] leading-4 text-[color:var(--text-muted)]">Демо-парсер понимает: «Клиент Альфа заплатит 300 000 рублей 20 ноября» и «Мы оплатим аренду 180 000 рублей 5 декабря».</p>
          <Button type="button" variant="outline" size="lg" onClick={parseNatural} disabled={!naturalText.trim()}>Распознать</Button>
          {parseError ? <div className="rounded-[5px] border border-[color:var(--border)] p-3 text-xs"><p>Не удалось однозначно распознать фразу. Проверьте шаблон или заполните форму вручную.</p><Button type="button" variant="outline" size="lg" className="mt-2" onClick={() => setCreateMode("manual")}>Открыть ручной ввод</Button></div> : null}
          {parsed ? <div className="rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface-subtle)] p-3 text-xs">
            <p className="font-semibold">Черновик для проверки</p>
            <dl className="mt-2 grid grid-cols-[94px_1fr] gap-x-2 gap-y-1"><dt className="text-[color:var(--text-muted)]">Событие</dt><dd>{draft.title}</dd><dt className="text-[color:var(--text-muted)]">Контрагент</dt><dd>{draft.counterparty}</dd><dt className="text-[color:var(--text-muted)]">Сумма</dt><dd>{formatMoney(draft.amount)}</dd><dt className="text-[color:var(--text-muted)]">Дата</dt><dd>{parseDate(draft.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</dd><dt className="text-[color:var(--text-muted)]">Направление</dt><dd>{draft.direction === "income" ? "Поступление" : "Списание"}</dd><dt className="text-[color:var(--text-muted)]">Категория</dt><dd>{draft.category}</dd></dl>
            <div className="mt-3 flex flex-wrap gap-2"><Button type="button" size="lg" onClick={createEvent}>Сохранить событие</Button><Button type="button" variant="outline" size="lg" onClick={() => setCreateMode("manual")}>Изменить вручную</Button></div>
          </div> : null}
        </div>}
      </Dialog>
      {notice ? <div role="status" className="fixed bottom-4 right-4 z-50 flex max-w-[min(420px,calc(100vw-32px))] items-center gap-3 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface-elevated)] px-3 py-2 text-xs text-[color:var(--text-primary)] shadow-none"><span>{notice.text}</span>{notice.undo ? <Button type="button" variant="outline" size="md" onClick={() => { const { id, oldDate } = notice.undo!; setEvents((current) => current.map((item) => item.id === id ? { ...item, date: oldDate } : item)); setSelectedDate(oldDate); setNotice({ text: "Перенос отменён. Остатки пересчитаны локально." }); }}>Отменить</Button> : <Button type="button" variant="ghost" size="md" aria-label="Закрыть уведомление" onClick={() => setNotice(null)}>×</Button>}</div> : null}
    </>
  );
}
