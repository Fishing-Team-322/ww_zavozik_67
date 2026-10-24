"use client";
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/src/features/auth";
import type { Schemas } from "@/src/shared/api";
import { queryParams } from "@/src/shared/api/query";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import {
  Button,
  Input,
  Select,
  EmptyState,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { money, percent, linkClass } from "./finance-utils";
import { PlanFactChart } from "./PlanFactChart";

type Missed = {
  missed: Array<Schemas["PlannedEvent"] & { days_late: number }>;
  unexpected: Schemas["Operation"][];
  data_as_of: string;
  forecast_change: {
    gap_date: string | null;
    gap_date_before: string | null;
    probability_before: number | null;
    probability_after: number | null;
    revision_before: number | null;
    revision_after: number | null;
  };
};
export function PlanFactScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [granularity, setGranularity] = useState("day");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [direction, setDirection] = useState<"in" | "out" | "net">("net");
  const rows = useApiResource<Schemas["PlanFactPoint"][]>(
    `${base}/plan-fact?${queryParams({ granularity, from, to })}`,
  );
  const missed = useApiResource<Missed>(`${base}/plan-fact/missed`);
  const change = missed.data?.forecast_change;
  return (
    <div className="space-y-5">
      <SectionCard className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-xl font-semibold">План и факт</h1>
          <Button
            variant="outline"
            onClick={() => {
              rows.refresh();
              missed.refresh();
            }}
          >
            Обновить
          </Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Select
            label="Группировка"
            value={granularity}
            options={[
              { value: "day", label: "По дням" },
              { value: "week", label: "По неделям" },
            ]}
            onChange={(e) => setGranularity(e.target.value)}
          />
          <Input
            label="С даты"
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => setFrom(e.target.value)}
          />
          <Input
            label="По дату"
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => setTo(e.target.value)}
          />
        </div>
        <FinanceState
          loading={rows.loading}
          error={rows.error}
          retry={rows.refresh}
        />
        {rows.data?.length === 0 && (
          <EmptyState title="Нет данных для сравнения" />
        )}
        {!!rows.data?.length && (
          <>
            <Select
              label="Показать на графике"
              value={direction}
              options={[
                { value: "net", label: "Чистый поток" },
                { value: "in", label: "Поступления" },
                { value: "out", label: "Списания" },
              ]}
              onChange={(e) => setDirection(e.target.value as typeof direction)}
            />
            <PlanFactChart rows={rows.data} direction={direction} />
            <p className="text-xs text-[color:var(--text-secondary)]">
              Пустой участок факта означает неполную выписку. Красным выделено
              отрицательное отклонение денежного потока от плана. Открытые
              экраны обновляются после обработки новых данных.
            </p>
            <Table>
              <TableHeader>
                <TableRow>
                  {[
                    "Период",
                    "План: поступления",
                    "Факт: поступления",
                    "План: списания",
                    "Факт: списания",
                    "Отклонение потока",
                  ].map((label) => (
                    <TableHead key={label}>{label}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.data.map((row) => (
                  <TableRow
                    key={row.period}
                    className={
                      row.deviation !== null && row.deviation < 0
                        ? "bg-[color:var(--danger-soft)]"
                        : undefined
                    }
                  >
                    <TableCell>
                      {row.period}
                      {!row.observed && (
                        <p className="text-xs">Выписка неполная</p>
                      )}
                    </TableCell>
                    {[
                      row.plan_in,
                      row.fact_in,
                      row.plan_out,
                      row.fact_out,
                      row.deviation,
                    ].map((value, index) => (
                      <TableCell key={index}>{money(value)}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </SectionCard>
      <SectionCard className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Несопоставленные платежи</h2>
        <p className="text-sm text-[color:var(--text-secondary)]">
          За последние 30 дней относительно актуальности выписки. Неоднозначные
          совпадения требуют проверки.
        </p>
        <FinanceState
          loading={missed.loading}
          error={missed.error}
          retry={missed.refresh}
        />
        {missed.data && (
          <>
            <p>Данные на {missed.data.data_as_of}</p>
            {change?.revision_before !== null &&
              change?.revision_before !== undefined && (
                <p className="rounded-md border border-[color:var(--border)] p-3 text-sm">
                  Сохранённые ревизии {change.revision_before} →{" "}
                  {change.revision_after}: вероятность разрыва{" "}
                  {percent(change.probability_before)} →{" "}
                  {percent(change.probability_after)}. Первый разрыв:{" "}
                  {change.gap_date_before ?? "не выявлен"} →{" "}
                  {change.gap_date ?? "не выявлен"}. Изменение отражает все
                  новые данные.
                </p>
              )}
            <h3 className="font-semibold">Ожидались, но не пришли</h3>
            {missed.data.missed.length === 0 && (
              <EmptyState title="Пропущенных платежей нет" />
            )}
            {missed.data.missed.map((event) => (
              <div
                key={event.id}
                className="flex flex-wrap justify-between gap-2 border-b border-[color:var(--border)] py-2"
              >
                <span>
                  {event.title} · {money(event.amount)} · {event.days_late} дн.
                </span>
                <Link
                  className={linkClass}
                  href={`/calendar?date=${event.date}&event=${event.id}`}
                >
                  {event.editable ? "Проверить и изменить" : "Открыть событие"}
                </Link>
              </div>
            ))}
            <h3 className="font-semibold">Факт без однозначного плана</h3>
            {missed.data.unexpected.length === 0 && (
              <EmptyState title="Неожиданных операций нет" />
            )}
            {missed.data.unexpected.map((row) => (
              <p key={row.id}>
                {row.date} · {row.counterparty.name} ·{" "}
                {row.direction === "in" ? "+" : "−"}
                {money(row.amount)} · {row.purpose}
              </p>
            ))}
          </>
        )}
      </SectionCard>
    </div>
  );
}
