"use client";

import { useState } from "react";
import { forecastReliability, riskProbability } from "@/src/entities/forecast";
import { useRouter } from "next/navigation";
import PulsOverview, { type PulsOverviewData } from "./PulsOverview";
import { ForecastNotice } from "@/app/[section]/_ui/FinanceState";
import { AccountGate, useSession } from "@/src/features/auth";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import type { Schemas } from "@/src/shared/api";
import { Button, Dialog } from "@/src/shared/ui";
import { CashflowSuggestions } from "@/src/widgets/finance-panels/ui/CashflowSuggestions";
import { ForecastDayDetails } from "@/src/widgets/finance-panels";
import { overviewDelayStep, overviewForecastPoints } from "@/src/entities/forecast/model/overview-adapters";

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
  const start = forecast?.as_of;
  const topGap = horizon === 30 ? dashboard?.top_gap : forecast?.gaps[0];
  const delayStep = forecast && dashboard ? overviewDelayStep(dashboard.upcoming_in, forecast.as_of, forecast.points.at(-1)?.date ?? forecast.as_of) : null;
  const scenarioPath = company && forecast ? `/v1/companies/${company.id}/scenarios/preview?horizon=${horizon}` : null;
  const delay = useApiResource<Schemas["ScenarioComparison"]>(delayStep ? scenarioPath : null, { method: "POST", json: { steps: delayStep ? [delayStep] : [] } });
  const downturn = useApiResource<Schemas["ScenarioComparison"]>(scenarioPath, { method: "POST", json: { steps: [{ kind: "scale_revenue", factor: 0.8 }] } });
  const scenarioError = delay.error || downturn.error;
  const data: PulsOverviewData | null =
    forecast && dashboard && dashboard.balance_now !== null
      ? {
          company: company?.name,
          currentBalance: dashboard.balance_now,
          safeToSpend: forecastReliability(forecast).spendingAvailable ? (horizon === 30 ? dashboard.safe_to_spend : forecast.safe_to_spend) : null,
          spendingAvailable: forecastReliability(forecast).spendingAvailable,
          forecastEnd: forecastReliability(forecast).end,
          minimumBalance: horizon === 30 ? dashboard.min_balance : undefined,
          reserve: company?.reserve,
          serverStatus: !forecastReliability(forecast).spendingAvailable && !topGap ? "warning" : horizon === 30 ? dashboard.status : forecast.status,
          headline: horizon === 30 ? dashboard.headline : forecast.headline,
          horizon,
          history: forecast.history.filter(p => p.date < forecast.as_of).map(p => ({ date: p.date, actual: p.balance })),
          isDemo: false,
          updatedAt: dashboard.data_as_of || undefined,
          forecast: overviewForecastPoints(forecast, delay.data, downturn.data),
          shortfallProbability: topGap ? riskProbability(topGap, forecast) : null,
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
      {(resource.error || extended.error || scenarioError) && (
        <p role="alert" className="mb-4 text-sm text-[color:var(--danger)]">
          {resource.error || extended.error || scenarioError}{" "}
          <Button variant="ghost" onClick={() => { resource.refresh(); extended.refresh(); delay.refresh(); downturn.refresh(); }}>
            Повторить
          </Button>
        </p>
      )}
      {forecast && <ForecastNotice forecast={forecast} />}
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
      {company && topGap && <CashflowSuggestions key={`${company.id}:${horizon}:${topGap.id}`} companyId={company.id} gap={topGap} horizon={horizon} />}
      <Dialog open={day !== null} title={`Прогноз на ${day ?? ""}`} onClose={() => setDay(null)} className="max-w-xl"
        headerActions={<Button variant="ghost" onClick={() => setDay(null)} aria-label="Закрыть детализацию дня">Закрыть</Button>}>
        {day && company && <ForecastDayDetails companyId={company.id} date={day} horizon={horizon} />}
      </Dialog>
    </AccountGate>
  );
}
