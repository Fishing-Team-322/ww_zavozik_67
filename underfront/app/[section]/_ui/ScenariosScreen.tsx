"use client";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import {
  api,
  message,
  type Forecast,
  type Schemas,
  type PlannedEvent,
} from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import {
  CashflowForecastChart,
  DEFAULT_SCENARIO,
  ScenarioControls,
  type ScenarioParams,
  RiskCard,
} from "@/src/widgets/finance-panels";
import { chartDays, riskView } from "@/src/entities/forecast";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function ScenariosScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const forecast = useApiResource<Forecast>(`${base}/forecast`);
  const events = useApiResource<PlannedEvent[]>(`${base}/events`);
  const [params, setParams] = useState<ScenarioParams>(DEFAULT_SCENARIO);
  const [counterparty, setCounterparty] = useState("");
  const [date, setDate] = useState("");
  const [title, setTitle] = useState("Мой сценарий");
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const steps: Schemas["ScenarioStep"][] = [];
  if (params.revenueDropPercent)
    steps.push({
      kind: "scale_revenue",
      factor: 1 - params.revenueDropPercent / 100,
    });
  if (params.unexpectedExpense && forecast.data)
    steps.push({
      kind: "add_expense",
      amount: params.unexpectedExpense,
      date: date || forecast.data.points[0].date,
    });
  if (params.paymentDelayDays && counterparty)
    steps.push({
      kind: "delay_counterparty",
      counterparty_id: counterparty,
      delay_days: params.paymentDelayDays,
    });
  const missingClient = params.paymentDelayDays > 0 && !counterparty;
  const compare = useApiResource<Schemas["ScenarioComparison"]>(
    steps.length && forecast.data && !missingClient
      ? `${base}/scenarios/preview`
      : null,
    { method: "POST", json: { steps } },
  );
  const clients = [
    ...new Map(
      (events.data || [])
        .filter(
          (event) =>
            event.direction === "in" &&
            event.status === "expected" &&
            event.date > (forecast.data?.as_of || "") &&
            event.counterparty.id,
        )
        .map((event) => [
          event.counterparty.id!,
          { value: event.counterparty.id!, label: event.counterparty.name },
        ]),
    ).values(),
  ];
  const result = compare.data?.scenario;
  const riskForecast = result || forecast.data;
  return (
    <>
      <FinanceState
        loading={forecast.loading || compare.loading}
        error={forecast.error || compare.error || error}
        retry={() => {
          forecast.refresh();
          compare.refresh();
        }}
      />
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
        <div className="space-y-4">
          <ScenarioControls
            value={params}
            onChange={(value) => {
              setParams(value);
              setSaved(null);
            }}
          />
          {params.paymentDelayDays > 0 && (
            <Select
              label="Клиент с плановым поступлением"
              placeholder="Выберите клиента"
              value={counterparty}
              onChange={(event) => setCounterparty(event.target.value)}
              options={clients}
            />
          )}
          {missingClient && (
            <p className="text-sm text-[color:var(--text-secondary)]">
              Для переноса выберите клиента с ожидаемым поступлением. Его можно
              добавить в календаре.
            </p>
          )}
          {params.unexpectedExpense > 0 && (
            <Input
              type="date"
              label="Дата внепланового расхода"
              min={forecast.data?.points[0]?.date}
              max={forecast.data?.points.at(-1)?.date}
              value={date || forecast.data?.points[0]?.date || ""}
              onChange={(event) => setDate(event.target.value)}
            />
          )}
          <Input
            label="Название сценария"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={200}
          />
          <Button
            disabled={!steps.length || missingClient || !compare.data}
            loading={saving}
            onClick={async () => {
              setSaving(true);
              setError(null);
              try {
                await api.request(`${base}/scenarios`, {
                  method: "POST",
                  json: { title, steps },
                });
                setSaved("Сценарий сохранён.");
              } catch (error) {
                setError(message(error));
              } finally {
                setSaving(false);
              }
            }}
          >
            Сохранить сценарий
          </Button>
          {saved && (
            <p role="status" className="text-sm">
              {saved}
            </p>
          )}
        </div>
        <SectionCard className="min-w-0 p-5">
          <h2 className="mb-4 text-lg font-semibold">
            Базовый и негативный прогноз
          </h2>
          <ForecastNotice forecast={compare.data?.base || forecast.data} />
          <CashflowForecastChart
            days={
              forecast.data
                ? chartDays(compare.data?.base || forecast.data, result)
                : []
            }
            showBounds
          />
          {!steps.length && (
            <p className="mt-4 text-sm text-[color:var(--text-secondary)]">
              Измените параметры, чтобы рассчитать сценарий.
            </p>
          )}
          <div className="mt-5">
            <RiskCard
              risk={
                riskForecast?.gaps[0] ? riskView(riskForecast.gaps[0]) : null
              }
              status={
                riskForecast && !riskForecast.gaps.length ? "clear" : "unknown"
              }
            />
          </div>
        </SectionCard>
      </div>
    </>
  );
}
