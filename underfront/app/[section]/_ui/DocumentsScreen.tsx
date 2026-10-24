"use client";
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/src/features/auth";
import { api, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select, Checkbox, Tabs, Dialog, ConfirmDialog, EmptyState, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { useAction, ActionFeedback, money, today, taxOptions, statusLabel, eventStatuses, fieldGrid, linkClass } from "./finance-utils";

type Invoice = Schemas["Invoice"];
type Contract = Schemas["Contract"];
type Kind = "invoices" | "contracts";
type Taxes = { tax_regime: string; items: Array<{ date: string; title: string; amount_estimate: number; how_calculated: string }> };
const invoiceStatuses = [{ value: "open", label: "Открыт" }, { value: "partial", label: "Частично оплачен" }, { value: "paid", label: "Оплачен" }, { value: "overdue", label: "Просрочен" }];
export function DocumentsScreen() {
  const [tab, setTab] = useState("invoices");
  return <div className="space-y-4"><h1 className="text-lg font-semibold">Счета, договоры и налоги</h1><Tabs value={tab} onValueChange={setTab} showContent={false} tabs={[{ key: "invoices", label: "Счета", content: null }, { key: "contracts", label: "Договоры", content: null }, { key: "taxes", label: "Налоги", content: null }]} />{tab === "taxes" ? <TaxesPanel /> : <DocumentsPanel key={tab} kind={tab as Kind} />}</div>;
}
function TaxesPanel() {
  const { company } = useSession();
  const [months, setMonths] = useState("3");
  const resource = useApiResource<Taxes>(`/v1/companies/${company!.id}/taxes?months=${months}`);
  return <SectionCard className="space-y-4 p-5"><p className="text-sm">Известные обязательства по подтверждённым регулярным платежам. Это не расчёт декларации или налога по ставке.</p><Select label="Период" value={months} options={[1, 3, 6, 12].map(n => ({ value: String(n), label: `${n} мес.` }))} onChange={e => setMonths(e.target.value)} /><FinanceState loading={resource.loading} error={resource.error} retry={resource.refresh} />{resource.data && <><p>Режим: {taxOptions.find(o => o.value === resource.data!.tax_regime)?.label ?? "Не указан"} · <Link className={linkClass} href="/settings">Изменить</Link></p>{resource.data.items.length === 0 ? <EmptyState title="Известных налоговых платежей нет" description="Подтвердите налоговые платежи в разделе регулярных платежей." /> : <Table><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead>Платёж</TableHead><TableHead>Оценка</TableHead></TableRow></TableHeader><TableBody>{resource.data.items.map((item, i) => <TableRow key={`${item.date}:${i}`}><TableCell>{item.date}</TableCell><TableCell>{item.title}<p className="text-xs text-[color:var(--text-secondary)]">{item.how_calculated}</p></TableCell><TableCell>{money(item.amount_estimate)}</TableCell></TableRow>)}</TableBody></Table>}</>}</SectionCard>;
}
function DocumentsPanel({ kind }: { kind: Kind }) {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}/${kind}`;
  const [status, setStatus] = useState("");
  const [direction, setDirection] = useState("");
  const filters = new URLSearchParams(Object.entries({ status, direction }).filter(([, value]) => value));
  const rows = useApiResource<Array<Invoice | Contract>>(`${base}?${filters}`);
  const [editing, setEditing] = useState<Invoice | Contract | "new" | null>(null);
  const [deleting, setDeleting] = useState<Invoice | Contract | null>(null);
  const action = useAction();
  return <SectionCard className="space-y-4 p-5"><Button onClick={() => setEditing("new")}>{kind === "invoices" ? "Добавить счёт" : "Добавить договор"}</Button>{kind === "invoices" && <div className={fieldGrid}><Select label="Статус" value={status} options={[{ value: "", label: "Все" }, ...invoiceStatuses]} onChange={e => setStatus(e.target.value)} /><Select label="Направление" value={direction} options={[{ value: "", label: "Все" }, { value: "issued", label: "Выставленные" }, { value: "received", label: "Полученные" }]} onChange={e => setDirection(e.target.value)} /></div>}
    <FinanceState loading={rows.loading} error={rows.error} retry={rows.refresh} /><ActionFeedback action={action} />{rows.data?.length === 0 && <EmptyState title="Документов пока нет" description="Добавленные документы появятся в платёжном календаре." />}
    {!!rows.data?.length && <Table><TableHeader><TableRow>{["Документ", "Сумма", "Оплата и сроки", "Действия"].map(v => <TableHead key={v}>{v}</TableHead>)}</TableRow></TableHeader><TableBody>{rows.data.map(row => <TableRow key={row.id}><TableCell>№ {row.number}<p>{row.counterparty.name}</p><p className="text-xs">{row.source === "manual" ? "Вручную" : row.source}</p></TableCell><TableCell>{money("amount" in row ? row.amount : row.total)}<p className="text-xs">{row.direction === "in" || row.direction === "issued" ? "Поступление" : "Списание"}</p></TableCell><TableCell>{"amount" in row ? <>{statusLabel(row.status)}<p>Оплачено: {money(row.paid_amount)}</p><p>Срок: {row.due_at}</p><p>Ожидается: {row.expected_pay_at}</p></> : row.schedule.map((payment, i) => <p key={i}>{payment.date}: {money(payment.amount)} · {statusLabel(payment.status)}</p>)}</TableCell><TableCell><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => setEditing(row)}>Изменить</Button><Button variant="ghost" size="sm" onClick={() => setDeleting(row)}>Удалить</Button><Link className={linkClass} href={`/calendar?date=${encodeURIComponent("due_at" in row ? row.due_at : row.schedule[0]?.date ?? today())}`}>Календарь</Link></div></TableCell></TableRow>)}</TableBody></Table>}
    {editing && <DocumentEditor key={editing === "new" ? "new" : editing.id} kind={kind} base={base} initial={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    <ConfirmDialog open={!!deleting} title="Удалить документ и его плановые события?" description={deleting?.number} loading={action.busy} onCancel={() => { if (!action.busy) setDeleting(null); }} onConfirm={() => void action.run(() => api.request(`/v1/${kind}/${deleting!.id}`, { method: "DELETE" }), () => setDeleting(null))}><ActionFeedback action={action} /></ConfirmDialog>
  </SectionCard>;
}
function DocumentEditor({ kind, base, initial, onClose }: { kind: Kind; base: string; initial: Invoice | Contract | null; onClose: () => void }) {
  const invoice = initial && "amount" in initial ? initial : null;
  const contract = initial && "total" in initial ? initial : null;
  const [schedule, setSchedule] = useState<Schemas["CreateContractInput"]["schedule"]>(contract?.schedule.map(item => ({ date: item.date, amount: item.amount, status: (["expected", "received", "missed", "cancelled"].includes(item.status) ? item.status : "expected") as NonNullable<Schemas["CreateContractInput"]["schedule"][number]["status"]> })) ?? [{ date: today(), amount: 0, status: "expected" }]);
  const action = useAction();
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = new FormData(e.currentTarget);
    const str = (key: string) => String(form.get(key) ?? "");
    const num = (key: string) => Number(form.get(key));
    const common = { number: str("number"), ...(str("counterparty_name").trim() ? { counterparty_name: str("counterparty_name").trim() } : {}), ...(str("counterparty_inn") ? { counterparty_inn: str("counterparty_inn") } : {}), ...(!initial ? { additional: form.get("additional") === "on" } : {}) };
    const input: Schemas["CreateInvoiceInput"] | Schemas["CreateContractInput"] = kind === "invoices"
      ? { ...common, direction: str("direction") as "issued" | "received", amount: num("amount"), paid_amount: num("paid_amount"), issued_at: str("issued_at"), due_at: str("due_at"), expected_pay_at: str("expected_pay_at"), status: str("status") as Schemas["CreateInvoiceInput"]["status"] }
      : { ...common, direction: str("direction") as "in" | "out", total: num("amount"), prepayment: num("prepayment"), deferral_days: num("deferral_days"), schedule };
    if ("paid_amount" in input && input.paid_amount! > input.amount) { action.setError("Оплаченная сумма не может превышать сумму счёта."); return; }
    void action.run(() => api.request(initial ? `/v1/${kind}/${initial.id}` : base, { method: initial ? "PATCH" : "POST", json: input }), onClose);
  }
  return <Dialog open title={kind === "invoices" ? "Счёт" : "Договор"} className="max-w-2xl" onClose={onClose} dismissDisabled={action.busy}><form className="space-y-4" onSubmit={submit}><div className={fieldGrid}><Input label="Номер" name="number" defaultValue={initial?.number} required maxLength={1024} /><Input label="Контрагент" name="counterparty_name" defaultValue={initial?.counterparty.name} maxLength={1024} />{!initial && <Input label="ИНН контрагента" name="counterparty_inn" pattern="[0-9]{10}([0-9]{2})?" maxLength={12} />}<Input label="Сумма, ₽" name="amount" type="number" min="0" max="10000000000000" step="0.01" required defaultValue={invoice?.amount ?? contract?.total} /><Select label="Направление" name="direction" defaultValue={initial?.direction ?? (kind === "invoices" ? "issued" : "in")} options={kind === "invoices" ? [{ value: "issued", label: "Выставленный счёт" }, { value: "received", label: "Полученный счёт" }] : [{ value: "in", label: "Поступление" }, { value: "out", label: "Списание" }]} />
      {kind === "invoices" ? <><Input label="Дата выставления" name="issued_at" type="date" required defaultValue={invoice?.issued_at ?? today()} /><Input label="Срок оплаты" name="due_at" type="date" required defaultValue={invoice?.due_at ?? today()} /><Input label="Ожидаемая дата оплаты" name="expected_pay_at" type="date" required defaultValue={invoice?.expected_pay_at ?? today()} /><Input label="Оплачено, ₽" name="paid_amount" type="number" min="0" step="0.01" required defaultValue={invoice?.paid_amount ?? 0} /><Select label="Статус" name="status" defaultValue={invoice?.status ?? "open"} options={invoiceStatuses} /></> : <><Input label="Предоплата, ₽" name="prepayment" type="number" min="0" step="0.01" required defaultValue={contract?.prepayment ?? 0} /><Input label="Отсрочка, дней" name="deferral_days" type="number" min="0" max="3650" required defaultValue={contract?.deferral_days ?? 0} /></>}</div>
    {kind === "contracts" && <div className="space-y-3"><h3 className="font-semibold">График платежей</h3>{schedule.map((item, i) => <div className="grid gap-2 sm:grid-cols-4" key={i}><Input label="Дата" type="date" required value={item.date} onChange={e => setSchedule(schedule.map((x, j) => j === i ? { ...x, date: e.target.value } : x))} /><Input label="Сумма, ₽" type="number" min="0" step="0.01" required value={item.amount} onChange={e => setSchedule(schedule.map((x, j) => j === i ? { ...x, amount: Number(e.target.value) } : x))} /><Select label="Статус" value={item.status ?? "expected"} options={eventStatuses} onChange={e => setSchedule(schedule.map((x, j) => j === i ? { ...x, status: e.target.value as typeof item.status } : x))} /><Button type="button" variant="ghost" disabled={schedule.length === 1} onClick={() => setSchedule(schedule.filter((_, j) => i !== j))}>Удалить строку</Button></div>)}<Button type="button" variant="outline" disabled={schedule.length >= 500} onClick={() => setSchedule([...schedule, { date: today(), amount: 0, status: "expected" }])}>Добавить дату</Button></div>}
    {!initial && <Checkbox name="additional" label="Добавить к прогнозу сверх обычного потока" />}
    <ActionFeedback action={action} /><Button type="submit" loading={action.busy}>Сохранить</Button></form></Dialog>;
}
