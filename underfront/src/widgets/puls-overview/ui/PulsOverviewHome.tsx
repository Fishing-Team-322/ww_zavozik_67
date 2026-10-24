"use client";

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
  const dashboard = resource.data;
  const forecast = dashboard?.forecast;
  const start = forecast?.points[0]?.date;
  const data: PulsOverviewData | null =
    forecast && dashboard.balance_now !== null
      ? {
          company: company?.name,
          currentBalance: dashboard.balance_now,
          isDemo: false,
          updatedAt: dashboard.data_as_of || undefined,
          forecast: forecast.points.map((point) => ({
            date: point.date,
            base: point.p50,
          })),
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
            ? "Используется упрощённый прогноз: основная модель временно недоступна."
            : "Надёжность прогноза ограничена. Проверьте полноту истории."}
        </p>
      )}
      <PulsOverview
        data={data}
        onAddSource={() => router.push("/sources")}
        onOpenForecast={() => router.push("/forecast")}
        onOpenCalendar={() => router.push("/calendar")}
        onOpenScenarios={() => router.push("/scenarios")}
      />
    </AccountGate>
  );
}
