"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { queryParams } from "@/src/shared/api/query";
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/src/features/auth";
import type { Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select, EmptyState, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { PlanFactChart } from "./PlanFactChart";
import { HistoricalBacktest } from "./HistoricalBacktest";
import { planFactProbability, type SavedForecastChange } from "@/src/entities/forecast/model/plan-fact";
import { money, percent, linkClass } from "./finance-utils";

type Missed = {
  missed: Array<Schemas["PlannedEvent"] & { days_late: number }>;
  unexpected: Schemas["Operation"][];
  data_as_of: string;
  forecast_change: SavedForecastChange;
};
export function PlanFactScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [granularity, setGranularity] = useState("day"); const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const [direction, setDirection] = useState<"in" | "out" | "net">("net");
  const [page, setPage] = useState(1);
  const [missedPage, setMissedPage] = useState(1);
  const [unexpectedPage, setUnexpectedPage] = useState(1);
  const rows = useApiResource<Schemas["PlanFactPoint"][]>(`${base}/plan-fact?${queryParams({ granularity, from, to })}`);
  const missed = useApiResource<Missed>(`${base}/plan-fact/missed`);
  const change = missed.data?.forecast_change;
  const probability = (side: "before" | "after") => {
    const value = change ? planFactProbability(change, side) : null;
    return value === null ? "Точная вероятность недоступна" : percent(value);
  };
  const totalPages = Math.max(1, Math.ceil((rows.data?.length ?? 0) / 10));
  const currentPage = Math.min(page, totalPages);
  const missedTotalPages = Math.max(1, Math.ceil((missed.data?.missed.length ?? 0) / 10));
  const unexpectedTotalPages = Math.max(1, Math.ceil((missed.data?.unexpected.length ?? 0) / 10));
  const currentMissedPage = Math.min(missedPage, missedTotalPages);
  const currentUnexpectedPage = Math.min(unexpectedPage, unexpectedTotalPages);
  return <div className="space-y-4">
    <ContentHeading level={1}>План и факт</ContentHeading>
    <HistoricalBacktest companyId={company!.id}/>
    <SectionCard className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <ContentHeading level={2}>Сохранённый план и факт</ContentHeading>
        <Button variant="outline" onClick={() => { rows.refresh(); missed.refresh(); }}>Обновить</Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Select density="form" label="Группировка" value={granularity} options={[{ value: "day", label: "По дням" }, { value: "week", label: "По неделям" }]} onChange={e => { setGranularity(e.target.value); setPage(1); }} />
        <Input label="С даты" type="date" value={from} max={to || undefined} onChange={e => { setFrom(e.target.value); setPage(1); }} />
        <Input label="По дату" type="date" value={to} min={from || undefined} onChange={e => { setTo(e.target.value); setPage(1); }} />
      </div>
      <FinanceState loading={rows.loading} error={rows.error} retry={rows.refresh} />
      {rows.data?.length === 0 && <EmptyState title="Нет данных для сравнения" />}
      {!!rows.data?.length && <>
        <Select density="form" label="Показать на графике" value={direction} options={[{ value: "net", label: "Чистый поток" }, { value: "in", label: "Поступления" }, { value: "out", label: "Списания" }]} onChange={e => setDirection(e.target.value as typeof direction)} />
        <PlanFactChart rows={rows.data} direction={direction} />
        <ContentText variant="description" tone="muted">Пустой участок плана означает, что план не был составлен. Это не нулевой поток. Сохранённый прогноз сравнивается с фактом только за даты после его создания. Пустой участок факта означает неполную выписку. Красным выделено отрицательное отклонение денежного потока от плана. Открытые экраны обновляются после обработки новых данных.</ContentText>
        <Table pagination={{ page: currentPage, totalPages, onPageChange: setPage }}>
          <TableHeader><TableRow>{["Период", "План: поступления", "Факт: поступления", "План: списания", "Факт: списания", "Отклонение потока"].map((label, index) => <TableHead numeric={index > 0} key={label}>{label}</TableHead>)}</TableRow></TableHeader>
          <TableBody>{rows.data.slice((currentPage - 1) * 10, currentPage * 10).map(row =>
            <TableRow key={row.period} className={row.deviation !== null && row.deviation < 0 ? "bg-[color:var(--danger-soft)]" : undefined}>
              <TableCell>{row.period}{!row.observed && <ContentText variant="meta">Выписка неполная</ContentText>}{row.plan_available === false && <ContentText variant="meta">План отсутствовал</ContentText>}{row.plan_basis === "documents" && <ContentText variant="meta">План документов</ContentText>}</TableCell>
              {[row.plan_in, row.fact_in, row.plan_out, row.fact_out, row.deviation].map((value, index) => <TableCell numeric key={index}>{money(value)}</TableCell>)}
            </TableRow>
          )}</TableBody>
        </Table>
      </>}
    </SectionCard>
    <SectionCard className="space-y-4">
      <ContentHeading level={2}>Несопоставленные платежи</ContentHeading>
      <ContentText variant="description" tone="muted">За последние 30 дней относительно актуальности выписки. Обычная выручка и расходы могут не иметь отдельного документа; это не означает ошибку. Неоднозначные совпадения требуют проверки.</ContentText>
      <FinanceState loading={missed.loading} error={missed.error} retry={missed.refresh} />
      {missed.data && <>
        <ContentText variant="body">Данные на {missed.data.data_as_of}</ContentText>
        {change?.revision_before !== null && change?.revision_before !== undefined &&
          <ContentText className="rounded-md border border-[color:var(--border)] p-3">
            Сохранённые ревизии {change.revision_before} → {change.revision_after}: вероятность разрыва {probability("before")} → {probability("after")}.
            Первый разрыв: {change.gap_date_before ?? "предупреждения нет"} → {change.gap_date ?? "предупреждения нет"}. Изменение отражает все новые данные. Оценка риска не гарантирует исход платежей.
          </ContentText>}

        <ContentHeading level={3}>Ожидались, но не пришли</ContentHeading>
        {missed.data.missed.length === 0 ? <EmptyState title="Пропущенных платежей нет" /> :
          <Table pagination={{ page: currentMissedPage, totalPages: missedTotalPages, onPageChange: setMissedPage }}>
            <TableHeader><TableRow><TableHead>Платёж</TableHead><TableHead>Дата</TableHead><TableHead numeric>Сумма</TableHead><TableHead numeric>Просрочка</TableHead><TableHead>Действие</TableHead></TableRow></TableHeader>
            <TableBody>{missed.data.missed.slice((currentMissedPage - 1) * 10, currentMissedPage * 10).map(event =>
              <TableRow key={event.id}><TableCell>{event.title}</TableCell><TableCell>{event.date}</TableCell><TableCell numeric>{money(event.amount)}</TableCell><TableCell numeric>{event.days_late} дн.</TableCell><TableCell><Link className={linkClass} href={`/calendar?date=${event.date}&event=${event.id}`}>{event.editable ? "Проверить и изменить" : "Открыть событие"}</Link></TableCell></TableRow>
            )}</TableBody>
          </Table>}
        <ContentHeading level={3}>Операции без привязки к документам</ContentHeading>
        {missed.data.unexpected.length === 0 ? <EmptyState title="Неожиданных операций нет" /> :
          <Table pagination={{ page: currentUnexpectedPage, totalPages: unexpectedTotalPages, onPageChange: setUnexpectedPage }}>
            <TableHeader><TableRow><TableHead>Дата</TableHead><TableHead>Контрагент</TableHead><TableHead>Назначение</TableHead><TableHead numeric>Сумма</TableHead></TableRow></TableHeader>
            <TableBody>{missed.data.unexpected.slice((currentUnexpectedPage - 1) * 10, currentUnexpectedPage * 10).map(row =>
              <TableRow key={row.id}><TableCell>{row.date}</TableCell><TableCell>{row.counterparty.name}</TableCell><TableCell>{row.purpose}</TableCell><TableCell numeric>{row.direction === "in" ? "+" : "−"}{money(row.amount)}</TableCell></TableRow>
            )}</TableBody>
          </Table>}
      </>}
    </SectionCard></div>;
}
