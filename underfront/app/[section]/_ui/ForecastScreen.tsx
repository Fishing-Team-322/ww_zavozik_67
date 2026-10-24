"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import type { Forecast } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Dialog, Select } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart, ForecastDayDetails, RiskCard } from "@/src/widgets/finance-panels";
import { chartDays, riskView, rubles } from "@/src/entities/forecast";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function ForecastScreen() {
  const { company } = useSession();
  const query = useSearchParams();
  const [horizon, setHorizon] = useState(["30", "60", "90"].includes(query.get("horizon") ?? "") ? query.get("horizon")! : String(company!.default_horizon));
  const scenario = query.get("scenario") ?? "";
  const [day, setDay] = useState<string | null>(null);
  const resource = useApiResource<Forecast>(
    `/v1/companies/${company!.id}/forecast?horizon=${horizon}${scenario ? `&scenario=${encodeURIComponent(scenario)}` : ""}`,
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
            <div className="w-[120px] shrink-0">
              <Select
                aria-label="Горизонт прогноза"
                size="md"
                fitContent
                value={horizon}
                onChange={(event) => { setDay(null); setHorizon(event.target.value); }}
                options={[30, 60, 90].map((n) => ({
                  value: String(n),
                  label: `${n} дней`,
                }))}
              />
            </div>
          </div>
          {scenario && <p className="text-sm">Выбран сохранённый сценарий · <Link className="underline" href="/forecast">Базовый прогноз</Link></p>}
          <ForecastNotice forecast={forecast} />
          <CashflowForecastChart
            days={forecast ? chartDays(forecast) : []}
            showBounds
            showScenario={false}
            onDayClick={setDay}
          />
          {forecast && (
            <p className="mt-4 text-sm">
              Можно потратить с учётом резерва:{" "}
              <strong>{rubles(forecast.safe_to_spend)}</strong>
            </p>
          )}
        </SectionCard>
        <div className="space-y-3"><RiskCard
          risk={forecast?.gaps[0] ? riskView(forecast.gaps[0]) : null}
          status={forecast && !forecast.gaps.length ? "clear" : "unknown"}
        />{forecast?.gaps[0] && !scenario && <Link className="text-sm text-[color:var(--accent)] underline" href={`/risks?gap=${encodeURIComponent(forecast.gaps[0].id)}&horizon=${horizon}`}>Разобрать причины нехватки</Link>}</div>
      </div>
      <Dialog open={!!day} title={day ? `Прогноз на ${day}` : undefined} onClose={() => setDay(null)} className="max-w-xl">
        {day && <ForecastDayDetails companyId={company!.id} date={day} horizon={horizon} scenario={scenario} />}
      </Dialog>
    </>
  );
}
