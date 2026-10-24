"use client";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import type { Forecast } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Select } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart, RiskCard } from "@/src/widgets/finance-panels";
import { chartDays, riskView, rubles } from "@/src/entities/forecast";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function ForecastScreen() {
  const { company } = useSession();
  const [horizon, setHorizon] = useState(String(company!.default_horizon));
  const resource = useApiResource<Forecast>(
    `/v1/companies/${company!.id}/forecast?horizon=${horizon}`,
  );
  const forecast = resource.data;
  return (
    <>
      <FinanceState
        loading={resource.loading}
        error={resource.error}
        retry={resource.refresh}
      />
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
        <SectionCard className="min-w-0 p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold">Денежный остаток</h2>
            <Select
              aria-label="Горизонт прогноза"
              value={horizon}
              onChange={(event) => setHorizon(event.target.value)}
              options={[30, 60, 90].map((n) => ({
                value: String(n),
                label: `${n} дней`,
              }))}
            />
          </div>
          <ForecastNotice forecast={forecast} />
          <CashflowForecastChart
            days={forecast ? chartDays(forecast) : []}
            showBounds
            showScenario={false}
          />
          {forecast && (
            <p className="mt-4 text-sm">
              Можно потратить с учётом резерва:{" "}
              <strong>{rubles(forecast.safe_to_spend)}</strong>
            </p>
          )}
        </SectionCard>
        <RiskCard
          risk={forecast?.gaps[0] ? riskView(forecast.gaps[0]) : null}
          status={forecast && !forecast.gaps.length ? "clear" : "unknown"}
        />
      </div>
    </>
  );
}
