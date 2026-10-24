"use client";

import type { DragEvent } from "react";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { formatCompactMoney, formatMoney } from "@/src/entities/payment";
import type { PaymentEvent } from "@/src/entities/payment";

interface PaymentEventCardProps {
  event: PaymentEvent;
  onOpen: (id: string) => void;
  compact?: boolean;
}

export function PaymentEventCard({ event, onOpen, compact = false }: PaymentEventCardProps) {
  const income = event.direction === "income";
  const uncertain = income && (event.status === "overdue" || (event.probability !== undefined && event.probability < 70));
  const tone = uncertain ? "text-[color:var(--warning)]" : income ? "text-[color:var(--accent)]" : "text-[color:var(--nav-item-active-text)]";
  const Icon = income ? ArrowDownLeft : ArrowUpRight;
  const status = event.direction === "income"
    ? { expected: "Ожидается", received: "Получено", overdue: "Просрочено", cancelled: "Отменено" }[event.status]
    : { expected: "Запланировано", received: "Оплачено", overdue: "Просрочен платёж", cancelled: "Отменено" }[event.status];

  function handleDragStart(dragEvent: DragEvent<HTMLButtonElement>) {
    dragEvent.dataTransfer.effectAllowed = "move";
    dragEvent.dataTransfer.setData("text/plain", event.id);
  }

  return (
    <button
      type="button"
      draggable
      onDragStart={handleDragStart}
      onClick={(clickEvent) => { clickEvent.stopPropagation(); onOpen(event.id); }}
      title={`${event.title} · ${formatMoney(event.amount)} · перетащите на другую дату`}
      className={`group flex w-full min-w-0 cursor-grab items-center gap-2 rounded-[4px] px-2 text-left transition-colors hover:bg-[color:var(--nav-item-hover-bg)] active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)] ${compact ? "min-h-11 py-1" : "min-h-12 py-1"} ${event.status === "cancelled" ? "opacity-50" : ""}`}
    >
      <span className={`flex size-6 shrink-0 items-center justify-center rounded-[4px] bg-[color:var(--sidebar-bg)] ${tone}`}><Icon size={14} strokeWidth={1.8} aria-hidden="true" /></span>
      <span className="min-w-0 flex-1">
        <span className={`block truncate text-[13px] font-medium leading-4 text-[color:var(--nav-item-active-text)] ${event.status === "cancelled" ? "line-through" : ""}`}>{event.title}</span>
        <span className="block truncate text-[12px] leading-4 text-[color:var(--nav-item-text)]">{event.counterparty} · {event.category} · {status}</span>
      </span>
      <span className={`shrink-0 text-right text-[13px] font-semibold leading-4 tabular-nums ${tone}`}>
        <span className="hidden sm:inline">{income ? "+" : "−"}{formatMoney(event.amount)}</span>
        <span className="sm:hidden">{income ? "+" : "−"}{formatCompactMoney(event.amount)} ₽</span>
      </span>
    </button>
  );
}
