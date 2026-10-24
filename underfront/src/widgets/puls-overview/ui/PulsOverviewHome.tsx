"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { fallbackNotice } from "@/src/entities/forecast";
import PulsOverview, { type PulsOverviewData } from "./PulsOverview";
import { AccountGate, useSession } from "@/src/features/auth";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import type { Schemas } from "@/src/shared/api";

export function PulsOverviewHome() {
  const router = useRouter();
  const { company } = useSession();
  const [horizon, setHorizon] = useState<30 | 60 | 90>(30);
  const resource = useApiResource<Schemas["Dashboard"]>(
    company ? `/v1/companies/${company.id}/dashboard?horizon=${horizon}` : null,
  );
  const dashboard = resource.data;
  const forecast = dashboard?.forecast;
  const start = forecast?.as_of;
  const data: PulsOverviewData | null =
    forecast && dashboard.balance_now !== null
      ? {
          company: company?.name,
          currentBalance: dashboard.balance_now,
          safeToSpend: forecast.safe_to_spend,
          reserve: company?.reserve,
          history: forecast.history.filter(point => point.date < forecast.as_of).map(point => ({ date: point.date, actual: point.balance })),
          isDemo: false,
          updatedAt: dashboard.data_as_of || undefined,
          forecast: [{ date: forecast.as_of, base: dashboard.balance_now, actual: dashboard.balance_now, p10: dashboard.balance_now, p50: dashboard.balance_now, p90: dashboard.balance_now }, ...forecast.points.map((point) => ({
            date: point.date,
            base: point.p50,
            p10: point.p10,
            p50: point.p50,
            p90: point.p90,
          }))],
          shortfallProbability: dashboard.top_gap?.probability ?? null,
          events: [...dashboard.upcoming_in, ...dashboard.upcoming_out].map(
            (event) => ({
              id: event.id,
              title: event.title,
              counterparty: event.counterparty.name,
              source: event.source,
              day: start
                ? Math.round(
                    (Date.parse(event.date) - Date.parse(start)) / 86400000,
                  )
                : 0,
              amount: event.direction === "in" ? event.amount : -event.amount,
              category:
                event.direction === "in"
                  ? "revenue"
                  : event.category === "salary"
                    ? "payroll"
                    : event.category === "tax"
                      ? "taxes"
                      : ["rent", "supplier"].includes(event.category)
                        ? "suppliers"
                        : "other",
            }),
          ),
        }
      : null;

  return (
    <AccountGate>
      {resource.loading && (
        <p role="status" className="mb-4 text-sm">
          Загружаем прогноз…
        </p>
      )}
      {resource.error && (
        <p role="alert" className="mb-4 text-sm text-[color:var(--danger)]">
          {resource.error}{" "}
          <button className="underline" onClick={resource.refresh}>
            Повторить
          </button>
        </p>
      )}
      {forecast?.low_confidence && (
        <p
          role="status"
          className="mb-4 text-sm text-[color:var(--text-secondary)]"
        >
          {forecast.fallback_used
            ? fallbackNotice(forecast.warnings)
            : "Надёжность прогноза ограничена. Проверьте полноту истории."}
        </p>
      )}
      {!resource.loading && !resource.error && <PulsOverview
        data={data}
        horizon={horizon}
        onChangeHorizon={setHorizon}
        onAddSource={() => router.push("/sources")}
        onOpenForecast={() => router.push("/forecast")}
        onOpenCalendar={() => router.push("/calendar")}
        onOpenScenarios={() => router.push("/scenarios")}
      />}
    </AccountGate>
  );
}
