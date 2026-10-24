"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import PulsOverview, { type PulsOverviewData } from "./PulsOverview";
import { AccountGate, useSession } from "@/src/features/auth";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import type { Schemas } from "@/src/shared/api";
import { Button, Dialog } from "@/src/shared/ui";
import { ForecastDayDetails } from "@/src/widgets/finance-panels";

// The dashboard adds payer_habit at runtime; it is not yet in the generated schema.
type DashboardResponse = Omit<Schemas["Dashboard"], "upcoming_in" | "upcoming_out"> & {
  upcoming_in: (Schemas["PlannedEvent"] & { payer_habit?: unknown })[];
  upcoming_out: (Schemas["PlannedEvent"] & { payer_habit?: unknown })[];
};

export function PulsOverviewHome() {
  const router = useRouter();
  const { company } = useSession();
  const resource = useApiResource<DashboardResponse>(
    company ? `/v1/companies/${company.id}/dashboard` : null,
  );
  const [horizon, setHorizon] = useState<30 | 60 | 90>(30);
  const extended = useApiResource<Schemas["Forecast"]>(company && horizon !== 30 ? `/v1/companies/${company.id}/forecast?horizon=${horizon}` : null);
  const [day, setDay] = useState<string | null>(null);
  const dashboard = resource.data;
  const forecast = horizon === 30 ? dashboard?.forecast : extended.data;
  const start = forecast?.points[0]?.date;
  const topGap = horizon === 30 ? dashboard?.top_gap : forecast?.gaps[0];
  const data: PulsOverviewData | null =
    forecast && dashboard && dashboard.balance_now !== null
      ? {
          company: company?.name,
          currentBalance: dashboard.balance_now,
          safeToSpend: horizon === 30 ? dashboard.safe_to_spend : forecast.safe_to_spend,
          minimumBalance: horizon === 30 ? dashboard.min_balance : undefined,
          reserve: company?.reserve,
          serverStatus: horizon === 30 ? dashboard.status : forecast.status,
          headline: horizon === 30 ? dashboard.headline : forecast.headline,
          horizon,
          history: forecast.history.map(p => ({ date: p.date, actual: p.balance })),
          isDemo: false,
          updatedAt: dashboard.data_as_of || undefined,
          forecast: forecast.points.map((point) => ({
            date: point.date,
            base: point.p50,
            p10: point.p10, p50: point.p50, p90: point.p90,
          })),
          shortfallProbability: topGap?.probability ?? null,
          events: [...dashboard.upcoming_in, ...dashboard.upcoming_out].map(
            (event) => ({
              id: event.id,
              title: event.title,
              counterparty: event.counterparty.name,
              source: event.source,
              paymentDiscipline: typeof event.payer_habit === "string" && event.payer_habit.trim() ? event.payer_habit : undefined,
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
          <Button variant="ghost" className="h-auto! border-0! p-0! text-[length:inherit]! text-inherit! underline hover:bg-transparent!" onClick={() => { resource.refresh(); extended.refresh(); }}>
            Повторить
          </Button>
        </p>
      )}
      {(horizon === 30 ? dashboard?.low_confidence : forecast?.low_confidence) && (
        <p
          role="status"
          className="mb-4 text-sm text-[color:var(--text-secondary)]"
        >
          {forecast?.fallback_used
            ? "Используется упрощённый прогноз: основная модель временно недоступна."
            : "Надёжность прогноза ограничена. Проверьте полноту истории."}
        </p>
      )}
      {!resource.loading && !extended.loading && !resource.error && !extended.error && <PulsOverview
        horizon={horizon}
        onChangeHorizon={value => { setDay(null); setHorizon(value); }}
        onOpenGap={topGap ? () => router.push(`/risks?gap=${encodeURIComponent(topGap.id)}&horizon=${horizon}`) : undefined}
        alerts={dashboard?.alerts ?? []}
        onOpenDay={setDay}
        data={data}
        onAddSource={() => router.push("/sources")}
        onOpenForecast={() => router.push(`/forecast?horizon=${horizon}`)}
        onOpenEvent={id => router.push(`/calendar?event=${encodeURIComponent(id)}`)}
        onOpenCalendar={() => router.push("/calendar")}
        onOpenScenarios={() => router.push("/scenarios")}
      />}
      <Dialog open={day !== null} title={`Прогноз на ${day ?? ""}`} onClose={() => setDay(null)} className="max-w-xl"
        headerActions={<Button variant="ghost" onClick={() => setDay(null)} aria-label="Закрыть детализацию дня">Закрыть</Button>}>
        {day && company && <ForecastDayDetails companyId={company.id} date={day} horizon={horizon} />}
      </Dialog>
    </AccountGate>
  );
}
