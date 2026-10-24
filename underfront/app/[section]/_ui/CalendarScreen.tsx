"use client";
import { useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, CircleHelp } from "lucide-react";
import { useSession } from "@/src/features/auth";
import { api, type Schemas, type PlannedEvent, type Forecast } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select, Checkbox, Dialog, ConfirmDialog, EmptyState } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { PaymentMonthGrid } from "@/src/features/payment-calendar/ui/PaymentMonthGrid";
import { PaymentBalanceChart } from "@/src/features/payment-calendar/ui/PaymentBalanceChart";
import { PaymentEventCard } from "@/src/features/payment-calendar/ui/PaymentEventCard";
import type { PaymentEvent } from "@/src/entities/payment";
import { CashflowForecastChart } from "@/src/widgets/finance-panels";
import { chartDays } from "@/src/entities/forecast";
import { FinanceState, ForecastNotice } from "./FinanceState";
import { useAction, ActionFeedback, money, today, directions, eventStatuses, fieldGrid, linkClass } from "./finance-utils";

export function CalendarScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const query = useSearchParams();
  const allEvents = useApiResource<PlannedEvent[]>(query.get("event") ? `${base}/events` : null);
  const linked = allEvents.data?.find(e => e.id === query.get("event"));
  const initialDate = query.get("date") || linked?.date || (company!.data_as_of || today()).slice(0, 10);
  const [chosenMonth, setMonth] = useState<string | null>(null);
  const month = chosenMonth ?? initialDate.slice(0, 7);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedDate = selected?.startsWith(month) ? selected : initialDate.startsWith(month) ? initialDate : `${month}-01`;
  const calendar = useApiResource<Schemas["Calendar"]>(`${base}/calendar?month=${month}`);
  const forecast = useApiResource<Forecast>(`${base}/forecast?horizon=90`);
  const [editing, setEditing] = useState<{ event: PlannedEvent | null; date: string } | null>(null);
  const [deleting, setDeleting] = useState<PlannedEvent | null>(null);
  const action = useAction();
  const events = calendar.data?.days.flatMap(day => day.events) ?? [];
  const eventView = (event: PlannedEvent): PaymentEvent => ({ id: event.id, title: event.title, counterparty: event.counterparty.name, amount: event.amount, date: event.date, direction: event.direction === "in" ? "income" : "expense", category: event.category, source: event.source, probability: event.probability * 100, status: event.status === "missed" ? "overdue" : event.status === "received" || event.status === "cancelled" ? event.status : "expected", manual: event.editable });
  const days = (calendar.data?.days ?? []).map((day, i, all) => ({ date: day.date, opening: all[i - 1]?.balance_p50 ?? null, closing: day.balance_p50, risk: day.risk, events: day.events.map(eventView) }));
  const day = calendar.data?.days.find(d => d.date === selectedDate);
  function openEvent(id: string, movedDate?: string) { const event = events.find(e => e.id === id) ?? linked; if (!event) return; setEditing({ event, date: movedDate ?? event.date }); }
  function moveMonth(offset: number) { const date = new Date(`${month}-01T12:00:00`); date.setMonth(date.getMonth() + offset); setMonth(date.toLocaleDateString("sv-SE").slice(0, 7)); }
  return <div className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-xl font-semibold">Платёжный календарь</h1><p className="text-sm text-[color:var(--text-secondary)]">Остатки и риски по расчёту сервиса, события из ваших источников.</p></div><Button onClick={() => setEditing({ event: null, date: selectedDate })}>+ Событие</Button></div><div className="flex flex-wrap items-center gap-2"><Button variant="outline" aria-label="Предыдущий месяц" onClick={() => moveMonth(-1)}>‹</Button><Input aria-label="Месяц" type="month" value={month} onChange={e => { if (e.target.value) setMonth(e.target.value); }} /><Button variant="outline" aria-label="Следующий месяц" onClick={() => moveMonth(1)}>›</Button><Button variant="outline" onClick={() => { setMonth(today().slice(0, 7)); setSelected(today()); }}>Сегодня</Button></div>
    <FinanceState loading={calendar.loading || allEvents.loading} error={calendar.error || allEvents.error} retry={() => { calendar.refresh(); allEvents.refresh(); }} /><ActionFeedback action={action} />
    {query.get("event") && linked && <Button variant="outline" onClick={() => openEvent(linked.id)}>Открыть: {linked.title}</Button>}
    {calendar.data && <div className="grid items-start gap-4 lg:grid-cols-[360px_minmax(0,1fr)]"><SectionCard className="p-4"><PaymentMonthGrid days={days} selectedDate={selectedDate} today={today()} onSelectDate={setSelected} onOpenEvent={id => openEvent(id)} onMoveEvent={(id, date) => { const event = events.find(e => e.id === id); if (event?.editable) openEvent(id, date); else action.setError("Это событие изменяется через документ или источник."); }} /></SectionCard><SectionCard className="space-y-4 p-4"><h2 className="font-semibold">{selectedDate}</h2><p className="text-sm flex items-center gap-2">{day?.risk === "danger" || day?.risk === "warning" ? <AlertTriangle size={16} /> : day?.risk === "ok" ? <CheckCircle2 size={16} /> : <CircleHelp size={16} />}{day?.risk === "danger" ? "Опасно" : day?.risk === "warning" ? "Внимание" : day?.risk === "ok" ? "Спокойно" : "Нет оценки"}</p><p>Прогнозный остаток: <strong>{money(day?.balance_p50)}</strong></p>{day?.events.length ? day.events.map(event => <div key={event.id} className="border-t border-[color:var(--border)] pt-3"><PaymentEventCard event={eventView(event)} onOpen={id => openEvent(id)} /><div className="flex gap-3">{event.editable && <Button variant="ghost" size="sm" onClick={() => openEvent(event.id)}>Изменить</Button>}{event.editable && event.source === "manual" && <Button variant="ghost" size="sm" onClick={() => setDeleting(event)}>Удалить</Button>}</div></div>) : <EmptyState title="На этот день событий нет" action={<Button onClick={() => setEditing({ event: null, date: selectedDate })}>Добавить</Button>} />}</SectionCard></div>}
    {calendar.data && <SectionCard className="space-y-3 p-4"><h2 className="font-semibold">Динамика остатка</h2><PaymentBalanceChart days={days} selectedDate={selectedDate} /><p className="text-xs text-[color:var(--text-secondary)]">Пустые участки означают отсутствие оценки, а не нулевой остаток. Прогноз ограничен 90 днями после даты выписки.</p></SectionCard>}
    {editing && <EventEditor key={`${editing.event?.id ?? "new"}:${editing.date}`} companyId={company!.id} initial={editing.event} date={editing.date} baseline={forecast.data} onClose={() => setEditing(null)} />}
    <ConfirmDialog open={!!deleting} title="Удалить событие из плана?" description={deleting?.title} loading={action.busy} onCancel={() => { if (!action.busy) setDeleting(null); }} onConfirm={() => void action.run(() => api.deleteEvent(deleting!.id), () => setDeleting(null))}><ActionFeedback action={action} /></ConfirmDialog>
  </div>;
}
function EventEditor({ companyId, initial, date, baseline, onClose }: { companyId: string; initial: PlannedEvent | null; date: string; baseline: Forecast | null; onClose: () => void }) {
  const [draft, setDraft] = useState<Schemas["CreateEventInput"]>({ title: initial?.title ?? "", date, amount: initial?.amount ?? 0, direction: initial?.direction ?? "out", category: (initial?.category as Schemas["Category"]) ?? "other", probability: initial?.probability ?? 1, status: initial?.status as Schemas["CreateEventInput"]["status"] ?? "expected", ...(initial?.counterparty.name ? { counterparty_name: initial.counterparty.name } : {}), ...(!initial ? { additional: true } : {}) });
  const [phrase, setPhrase] = useState(""); const action = useAction();
  const [previewInput, setPreviewInput] = useState<typeof draft | null>(null);
  const categories = useApiResource<Array<{ key: Schemas["Category"]; title: string }>>("/v1/categories");
  const preview = useApiResource<{ forecast: Forecast }>(previewInput ? `/v1/companies/${companyId}/forecast/preview?horizon=90` : null, { method: "POST", json: initial ? { changes: [{ ...previewInput, id: initial.id }] } : { events: [previewInput] } });
  const editable = !initial || initial.editable;
  function change(values: Partial<typeof draft>) { setDraft({ ...draft, ...values }); setPreviewInput(null); }
  return <Dialog open title={initial ? initial.title : "Новое событие"} className="max-w-3xl" onClose={onClose} dismissDisabled={action.busy}>
    {!editable ? <div className="space-y-4"><p>{initial!.date} · {money(initial!.amount)} · {initial!.counterparty.name}</p><p>Событие управляется документом или источником.</p><Link className={linkClass} href={initial!.source === "recurring" ? "/recurring" : initial!.source === "manual" ? "/calendar" : ["invoice", "contract"].includes(initial!.source) ? "/documents" : "/sources"}>Открыть связанный раздел</Link></div> : <form className="space-y-4" onSubmit={e => { e.preventDefault(); void action.run(() => initial ? api.updateEvent(initial.id, draft) : api.createEvent(companyId, draft), onClose); }}>
      {!initial && <div className="space-y-2"><Input label="Опишите платёж" value={phrase} maxLength={500} onChange={e => setPhrase(e.target.value)} placeholder="Клиент заплатит 300 тысяч 20-го" /><Button type="button" variant="outline" disabled={!phrase.trim() || action.busy} onClick={() => void action.run(() => api.request<Schemas["CreateEventInput"]>(`/v1/companies/${companyId}/events/parse`, { method: "POST", json: { text: phrase } }), parsed => { setDraft({ title: parsed.title, date: parsed.date, amount: parsed.amount, direction: parsed.direction, category: parsed.category, probability: parsed.probability, ...(parsed.counterparty_name ? { counterparty_name: parsed.counterparty_name } : {}), additional: true }); setPreviewInput(null); }, "Это черновик. Проверьте поля и подтвердите сохранение.")}>Заполнить по описанию</Button></div>}
      <div className={fieldGrid}><Input label="Название" value={draft.title} maxLength={1024} required onChange={e => change({ title: e.target.value })} /><Input label="Контрагент" value={draft.counterparty_name ?? ""} maxLength={1024} onChange={e => change({ counterparty_name: e.target.value || undefined })} /><Input label="Дата" type="date" value={draft.date} required onChange={e => change({ date: e.target.value })} /><Input label="Сумма, ₽" type="number" min="0.01" max="10000000000000" step="0.01" value={draft.amount} required onChange={e => change({ amount: Number(e.target.value) })} /><Select label="Направление" value={draft.direction} options={directions} onChange={e => change({ direction: e.target.value as "in" | "out" })} /><Select label="Категория" value={draft.category ?? "other"} options={(categories.data ?? []).map(c => ({ value: c.key, label: c.title }))} onChange={e => change({ category: e.target.value as Schemas["Category"] })} /><Input label="Вероятность, %" type="number" min="0" max="100" value={(draft.probability ?? 1) * 100} onChange={e => change({ probability: Number(e.target.value) / 100 })} /><Select label="Статус" value={draft.status ?? "expected"} options={eventStatuses} onChange={e => change({ status: e.target.value as typeof draft.status })} /></div>
      {!initial && <Checkbox label="Добавить сверх обычного потока" checked={draft.additional} onChange={e => change({ additional: e.target.checked })} />}<FinanceState loading={categories.loading} error={categories.error} retry={categories.refresh} /><ActionFeedback action={action} /><div className="flex flex-wrap gap-3"><Button type="button" variant="outline" disabled={!draft.title || !draft.date || draft.amount <= 0 || preview.loading || action.busy} onClick={() => setPreviewInput({ ...draft })}>Посмотреть прогноз до сохранения</Button><Button type="submit" loading={action.busy}>Сохранить событие</Button><Button type="button" variant="ghost" disabled={action.busy} onClick={onClose}>Отмена</Button></div>
      <FinanceState loading={preview.loading} error={preview.error} retry={preview.refresh} />{preview.data && <><ForecastNotice forecast={preview.data.forecast} /><CashflowForecastChart days={chartDays(baseline ?? preview.data.forecast, preview.data.forecast)} showBounds /><p className="text-sm">Доступно после изменения: {money(preview.data.forecast.safe_to_spend)}. Предпросмотр не сохранён.</p></>}
    </form>}
  </Dialog>;
}
