"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import PulsOverview, { type PulsOverviewData } from "./PulsOverview";
import { AccountGate, useSession } from "@/src/features/auth";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import type { Schemas } from "@/src/shared/api";

export function PulsOverviewHome() {
  const router = useRouter();
  const { company } = useSession();
  const resource = useApiResource<Schemas["Dashboard"]>(
    company ? `/v1/companies/${company.id}/dashboard` : null,
  );
  const [horizon, setHorizon] = useState<30 | 60 | 90>(30);
  const extended = useApiResource<Schemas["Forecast"]>(company && horizon !== 30 ? `/v1/companies/${company.id}/forecast?horizon=${horizon}` : null);
  const dashboard = resource.data;
  const forecast = horizon === 30 ? dashboard?.forecast : extended.data;
  const start = forecast?.points[0]?.date;
  const data: PulsOverviewData | null =
    forecast && dashboard && dashboard.balance_now !== null
      ? {
          company: company?.name,
          currentBalance: dashboard.balance_now,
          safeToSpend: forecast.safe_to_spend,
          reserve: company?.reserve,
          serverStatus: forecast.status,
          headline: forecast.headline,
          horizon,
          history: forecast.history.filter((p): p is { date: string; balance: number } => p.balance !== null).map(p => ({ date: p.date, actual: p.balance })),
          isDemo: false,
          updatedAt: dashboard.data_as_of || undefined,
          forecast: forecast.points.map((point) => ({
            date: point.date,
            base: point.p50,
            p10: point.p10, p50: point.p50, p90: point.p90,
          })),
          shortfallProbability: forecast.gaps[0]?.probability ?? null,
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
      {(resource.loading || extended.loading) && (
        <p role="status" className="mb-4 text-sm">
          Загружаем прогноз…
        </p>
      )}
      {(resource.error || extended.error) && (
        <p role="alert" className="mb-4 text-sm text-[color:var(--danger)]">
          {resource.error || extended.error}{" "}
          <button className="underline" onClick={() => { resource.refresh(); extended.refresh(); }}>
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
            ? "Используется упрощённый прогноз: основная модель временно недоступна."
            : "Надёжность прогноза ограничена. Проверьте полноту истории."}
        </p>
      )}
      {!resource.loading && !extended.loading && !resource.error && !extended.error && <PulsOverview
        horizon={horizon}
        onChangeHorizon={setHorizon}
        onOpenGap={forecast?.gaps[0] ? () => router.push(`/risks?gap=${encodeURIComponent(forecast.gaps[0].id)}&horizon=${horizon}`) : undefined}
        data={data}
        onAddSource={() => router.push("/sources")}
        onOpenForecast={() => router.push(`/forecast?horizon=${horizon}`)}
        onOpenEvent={id => router.push(`/calendar?event=${encodeURIComponent(id)}`)}
        onOpenCalendar={() => router.push("/calendar")}
        onOpenScenarios={() => router.push("/scenarios")}
      />}
    </AccountGate>
  );
}
