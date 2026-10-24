"use client";

import { useEffect, useRef } from "react";
import { Button } from "@/src/shared/ui/button";
import { PaymentEventForm } from "./PaymentEventForm";
import { formatMoney, parseDate } from "@/src/entities/payment";
import type { PaymentDraft, PaymentEvent } from "@/src/entities/payment";

interface PaymentEventPanelProps {
  event: PaymentEvent | null;
  editing: boolean;
  draft: PaymentDraft;
  onDraftChange: (draft: PaymentDraft) => void;
  onClose: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: () => void;
  onDelete: () => void;
}

export function PaymentEventPanel({ event, editing, draft, onDraftChange, onClose, onEdit, onCancelEdit, onSave, onDelete }: PaymentEventPanelProps) {
  const panelRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  const eventId = event?.id;
  useEffect(() => {
    if (!eventId) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (keyEvent: KeyboardEvent) => { if (keyEvent.key === "Escape") onCloseRef.current(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); previousFocus?.focus(); };
  }, [eventId]);
  if (!event) return null;
  const rows = [
    ["Контрагент", event.counterparty],
    ["Дата", parseDate(event.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })],
    ["Направление", event.direction === "income" ? "Поступление" : "Списание"],
    ["Категория", event.category],
    ["Источник данных", event.source],
    ["Статус", event.direction === "income"
      ? { expected: "Ожидается", received: "Получено", overdue: "Просрочено", cancelled: "Отменено" }[event.status]
      : { expected: "Запланировано", received: "Оплачено", overdue: "Просрочен платёж", cancelled: "Отменено" }[event.status]],
    ...(event.direction === "income" ? [["Вероятность", event.probability === undefined ? "Не указана" : `${event.probability}%`]] : []),
  ];
  return (
    <div className="fixed inset-0 z-40">
      <button type="button" aria-label="Закрыть сведения о событии" onClick={onClose} className="absolute inset-0 bg-[color:var(--page-bg)]/70" />
      <aside ref={panelRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`Событие: ${event.title}`} className="absolute inset-y-0 right-0 flex w-full max-w-[420px] flex-col border-l border-[color:var(--border)] bg-[color:var(--surface)] text-[color:var(--text-primary)] outline-none sm:shadow-none">
        <div className="flex items-start justify-between gap-3 border-b border-[color:var(--border)] px-5 py-4">
          <div className="min-w-0"><p className="text-[11px] font-medium uppercase tracking-wide text-[color:var(--text-muted)]">Финансовое событие</p><h2 className="mt-1 text-base font-semibold">{event.title}</h2></div>
          <Button type="button" variant="ghost" size="lg" aria-label="Закрыть" onClick={onClose}>×</Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {editing ? <PaymentEventForm draft={draft} onChange={onDraftChange} onSubmit={onSave} submitLabel="Сохранить" onCancel={onCancelEdit} /> : <>
            <div className={`mb-5 text-2xl font-semibold tabular-nums ${event.direction === "income" ? "text-[color:var(--accent)]" : "text-[color:var(--text-primary)]"}`}>{event.direction === "income" ? "+" : "−"}{formatMoney(event.amount)}</div>
            <dl className="divide-y divide-[color:var(--border)] border-y border-[color:var(--border)]">{rows.map(([label, value]) => <div key={label} className="grid grid-cols-[120px_1fr] gap-3 py-2.5 text-xs"><dt className="text-[color:var(--text-muted)]">{label}</dt><dd className="font-medium">{value}</dd></div>)}</dl>
            <div className="mt-5 flex flex-wrap gap-2"><Button type="button" size="lg" onClick={onEdit}>Редактировать</Button>{event.manual ? <Button type="button" variant="outline" size="lg" onClick={onDelete}>Удалить</Button> : null}</div>
            <p className="mt-5 text-[11px] leading-4 text-[color:var(--text-muted)]">Для переноса на телефоне откройте «Редактировать» и выберите новую дату.</p>
          </>}
        </div>
      </aside>
    </div>
  );
}
