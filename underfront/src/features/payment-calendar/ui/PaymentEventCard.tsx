"use client";
import { contentTypography } from "@/src/shared/ui/content";

import type { DragEvent, ReactNode } from "react";
import { ArrowDownLeft, ArrowUpRight } from "lucide-react";
import { formatCompactMoney, formatMoney } from "@/src/entities/payment";
import type { PaymentEvent } from "@/src/entities/payment";

interface PaymentEventCardProps {
  event: PaymentEvent;
  onOpen: (id: string) => void;
  compact?: boolean;
  detailed?: boolean;
  actions?: ReactNode;
}

const categoryLabels: Record<string, string> = {
  revenue_acquiring: "Эквайринг", revenue_sbp: "СБП", revenue_cash: "Наличные", revenue_b2b: "Клиенты", revenue_marketplace: "Маркетплейсы",
  supplier: "Поставщики", salary: "Зарплата", tax: "Налоги", rent: "Аренда", utilities: "Коммунальные услуги",
  loan_payment: "Кредит", leasing: "Лизинг", bank_fee: "Комиссия банка", marketing: "Маркетинг", services: "Услуги",
  own_transfer: "Перевод между счетами", owner_loan: "Заём владельца", refund: "Возврат", enforcement: "Взыскание", other: "Прочее",
};

export function PaymentEventCard({ event, onOpen, compact = false, detailed = false, actions }: PaymentEventCardProps) {
  const income = event.direction === "income";
  const uncertain = income && (event.status === "overdue" || (event.probability !== undefined && event.probability < 70));
  const tone = uncertain ? "text-[color:var(--warning)]" : income ? "text-[color:var(--accent)]" : detailed ? "text-[color:var(--text-primary)]" : "text-[color:var(--nav-item-active-text)]";
  const Icon = income ? ArrowDownLeft : ArrowUpRight;
  const status = event.direction === "income"
    ? { expected: "Ожидается", received: "Получено", overdue: "Просрочено", cancelled: "Отменено" }[event.status]
    : { expected: "Запланировано", received: "Оплачено", overdue: "Просрочен платёж", cancelled: "Отменено" }[event.status];

  function handleDragStart(dragEvent: DragEvent<HTMLButtonElement>) {
    dragEvent.dataTransfer.effectAllowed = "move";
    dragEvent.dataTransfer.setData("text/plain", event.id);
  }

  if (detailed) return (
    <div className={`min-w-0 rounded-[4px] border border-[color:var(--border)] p-3 ${event.status === "cancelled" ? "opacity-50" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${tone}`}><Icon size={16} strokeWidth={1.8} aria-hidden="true" />{income ? "Поступление" : "Списание"} · {status}</span>
        <span className={`font-semibold tabular-nums ${tone}`}>{income ? "+" : "−"}{formatMoney(event.amount)}</span>
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-2">
        <button
          type="button"
          draggable
          onDragStart={handleDragStart}
          onClick={(clickEvent) => { clickEvent.stopPropagation(); onOpen(event.id); }}
          title={`${event.title} · ${formatMoney(event.amount)} · перетащите на другую дату`}
          className={`min-w-0 flex-1 cursor-grab truncate text-left font-medium text-[color:var(--text-primary)] hover:underline active:cursor-grabbing focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)] ${event.status === "cancelled" ? "line-through" : ""}`}
        >{event.title}</button>
      </div>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-2 border-t border-[color:var(--border)] pt-2">
        <p className="min-w-0 truncate text-xs text-[color:var(--text-secondary)]">
          {event.counterparty || "Без контрагента"} · {categoryLabels[event.category] ?? event.category}
        </p>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
    </div>
  );

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
        <span className={`block truncate ${contentTypography.financial} text-[color:var(--nav-item-active-text)] ${event.status === "cancelled" ? "line-through" : ""}`}>{event.title}</span>
        <span className={`block truncate text-[color:var(--nav-item-text)] ${contentTypography.meta}`}>{event.counterparty} · {event.category} · {status}</span>
      </span>
      <span className={`shrink-0 text-right ${contentTypography.financial} ${tone}`}>
        <span className="hidden sm:inline">{income ? "+" : "−"}{formatMoney(event.amount)}</span>
        <span className="sm:hidden">{income ? "+" : "−"}{formatCompactMoney(event.amount)} ₽</span>
      </span>
    </button>
  );
}
