"use client";

import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";
import { PAYMENT_CATEGORIES } from "@/src/entities/payment";
import type { PaymentDraft, PaymentStatus } from "@/src/entities/payment";

interface PaymentEventFormProps {
  draft: PaymentDraft;
  onChange: (draft: PaymentDraft) => void;
  onSubmit: () => void;
  submitLabel: string;
  onCancel?: () => void;
}

export function PaymentEventForm({ draft, onChange, onSubmit, submitLabel, onCancel }: PaymentEventFormProps) {
  const update = (partial: Partial<PaymentDraft>) => onChange({ ...draft, ...partial });
  const statusOptions = draft.direction === "income"
    ? [{ value: "expected", label: "Ожидается" }, { value: "received", label: "Получено" }, { value: "overdue", label: "Просрочено" }, { value: "cancelled", label: "Отменено" }]
    : [{ value: "expected", label: "Запланировано" }, { value: "received", label: "Оплачено" }, { value: "overdue", label: "Просрочен платёж" }, { value: "cancelled", label: "Отменено" }];
  return (
    <form onSubmit={(event) => { event.preventDefault(); onSubmit(); }} className="space-y-3">
      <Input inputSize="lg" label="Название" value={draft.title} onChange={(event) => update({ title: event.target.value })} required placeholder="Например, оплата по договору" />
      <Input inputSize="lg" label="Контрагент" value={draft.counterparty} onChange={(event) => update({ counterparty: event.target.value })} required placeholder="Название компании" />
      <div className="grid grid-cols-2 gap-3">
        <Input inputSize="lg" label="Сумма, ₽" type="number" min="1" step="1" value={draft.amount || ""} onChange={(event) => update({ amount: Number(event.target.value) })} required />
        <Input inputSize="lg" label="Дата" type="date" value={draft.date} onChange={(event) => update({ date: event.target.value })} required />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Select size="lg" label="Направление" value={draft.direction} onChange={(event) => update({ direction: event.target.value as PaymentDraft["direction"] })} options={[{ value: "income", label: "Поступление" }, { value: "expense", label: "Списание" }]} />
        <Select size="lg" label="Категория" value={draft.category} onChange={(event) => update({ category: event.target.value })} options={PAYMENT_CATEGORIES.map((category) => ({ value: category, label: category }))} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Select size="lg" label="Статус" value={draft.status} onChange={(event) => update({ status: event.target.value as PaymentStatus })} options={statusOptions} />
        {draft.direction === "income" ? <Input inputSize="lg" label="Вероятность, %" type="number" min="0" max="100" value={draft.probability ?? ""} onChange={(event) => update({ probability: event.target.value === "" ? undefined : Number(event.target.value) })} /> : <div />}
      </div>
      <div className="flex justify-end gap-2 border-t border-[color:var(--border)] pt-4">
        {onCancel ? <Button type="button" variant="outline" size="lg" onClick={onCancel}>Отмена</Button> : null}
        <Button type="submit" size="lg">{submitLabel}</Button>
      </div>
    </form>
  );
}
