"use client";
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/src/features/auth";
import type { Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Input, Select, EmptyState, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { money, linkClass } from "./finance-utils";

type Missed = { missed: Array<Schemas["PlannedEvent"] & { days_late: number }>; unexpected: Schemas["Operation"][]; data_as_of: string };
export function PlanFactScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [granularity, setGranularity] = useState("day"); const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const rows = useApiResource<Schemas["PlanFactPoint"][]>(`${base}/plan-fact?${new URLSearchParams(Object.entries({ granularity, from, to }).filter(([, value]) => value !== ""))}`);
  const missed = useApiResource<Missed>(`${base}/plan-fact/missed`);
  return <div className="space-y-4"><SectionCard className="space-y-4 p-5"><h1 className="text-lg font-semibold">План и факт</h1><div className="grid gap-3 sm:grid-cols-3"><Select label="Группировка" value={granularity} options={[{ value: "day", label: "По дням" }, { value: "week", label: "По неделям" }]} onChange={e => setGranularity(e.target.value)} /><Input label="С даты" type="date" value={from} max={to || undefined} onChange={e => setFrom(e.target.value)} /><Input label="По дату" type="date" value={to} min={from || undefined} onChange={e => setTo(e.target.value)} /></div><FinanceState loading={rows.loading} error={rows.error} retry={rows.refresh} />{rows.data?.length === 0 && <EmptyState title="Нет данных для сравнения" />}{!!rows.data?.length && <Table><TableHeader><TableRow>{["Период", "План: поступления", "Факт: поступления", "План: списания", "Факт: списания", "Отклонение потока"].map(x => <TableHead key={x}>{x}</TableHead>)}</TableRow></TableHeader><TableBody>{rows.data.map(row => <TableRow key={row.period}><TableCell>{row.period}</TableCell>{[row.plan_in, row.fact_in, row.plan_out, row.fact_out, row.deviation].map((n, i) => <TableCell key={i}>{money(n)}</TableCell>)}</TableRow>)}</TableBody></Table>}</SectionCard>
    <SectionCard className="space-y-4 p-5"><h2 className="font-semibold">Несопоставленные платежи</h2><p className="text-sm text-[color:var(--text-secondary)]">За последние 30 дней относительно актуальности выписки. Неоднозначные совпадения требуют проверки.</p><FinanceState loading={missed.loading} error={missed.error} retry={missed.refresh} />{missed.data && <><p className="text-sm">Данные на {missed.data.data_as_of}</p><h3 className="font-semibold">Ожидались, но не пришли</h3>{missed.data.missed.length === 0 && <EmptyState title="Пропущенных платежей нет" />}{missed.data.missed.map(event => <div key={event.id} className="flex flex-wrap justify-between gap-2 border-b border-[color:var(--border)] py-2"><span>{event.title} · {money(event.amount)} · {event.days_late} дн.</span><Link className={linkClass} href={`/calendar?date=${event.date}&event=${event.id}`}>{event.editable ? "Проверить и изменить" : "Открыть событие"}</Link></div>)}<h3 className="font-semibold">Факт без однозначного плана</h3>{missed.data.unexpected.length === 0 && <EmptyState title="Неожиданных операций нет" />}{missed.data.unexpected.map(row => <p key={row.id}>{row.date} · {row.counterparty.name} · {row.direction === "in" ? "+" : "−"}{money(row.amount)} · {row.purpose}</p>)}</>}</SectionCard></div>;
}
