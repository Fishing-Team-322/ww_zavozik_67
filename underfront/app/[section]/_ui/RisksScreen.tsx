"use client";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import {
  api,
  message,
  type Forecast,
  type Schemas,
  type Gap,
} from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { RiskCard, CashflowForecastChart } from "@/src/widgets/finance-panels";
import { chartDays, riskView, rubles } from "@/src/entities/forecast";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function RisksScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const forecast = useApiResource<Forecast>(`${base}/forecast`);
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <FinanceState
        loading={forecast.loading}
        error={forecast.error}
        retry={forecast.refresh}
      />
      <ForecastNotice forecast={forecast.data} />
      {forecast.data?.gaps.length === 0 && (
        <RiskCard risk={null} status="clear" />
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {forecast.data?.gaps.map((gap) => (
          <div key={gap.id}>
            <RiskCard risk={riskView(gap)} />
            <Button
              variant="outline"
              className="mt-3"
              onClick={() => setSelected(gap.id)}
            >
              Причины и действия
            </Button>
          </div>
        ))}
      </div>
      {forecast.data &&
        selected &&
        forecast.data.gaps.some((gap) => gap.id === selected) && (
          <GapDetails
            key={selected}
            base={base}
            gap={forecast.data.gaps.find((gap) => gap.id === selected)!}
            forecast={forecast.data}
            onApplied={forecast.refresh}
          />
        )}
    </>
  );
}
function GapDetails({
  base,
  gap,
  forecast,
  onApplied,
}: {
  base: string;
  gap: Gap;
  forecast: Forecast;
  onApplied: () => void;
}) {
  const detail = useApiResource<Schemas["GapDetail"]>(
    `${base}/gaps/${encodeURIComponent(gap.id)}`,
  );
  const [ids, setIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const simulated = useApiResource<Schemas["GapSimulation"]>(
    ids.length ? `${base}/gaps/${encodeURIComponent(gap.id)}/simulate` : null,
    { method: "POST", json: { action_ids: ids } },
  );
  return (
    <SectionCard className="mt-5 space-y-4 p-5">
      <h2 className="text-lg font-semibold">Что влияет на разрыв</h2>
      <FinanceState
        loading={detail.loading || simulated.loading}
        error={detail.error || simulated.error || error}
        retry={() => {
          detail.refresh();
          simulated.refresh();
        }}
      />
      {detail.data && (
        <>
          <ul className="list-inside list-disc space-y-2 text-sm">
            {detail.data.causes.map((cause) => (
              <li key={cause.component_key}>
                {cause.title}: {rubles(cause.amount)}
              </li>
            ))}
          </ul>
          <p className="text-sm text-[color:var(--text-secondary)]">
            Также учитывается ожидаемый поток бизнеса по модели. Выберите
            действия, чтобы проверить их эффект.
          </p>
          {detail.data.actions.map((action) => (
            <div
              key={action.id}
              className="rounded-lg border border-[color:var(--border)] p-4"
            >
              <label className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={ids.includes(action.id)}
                  onChange={(event) =>
                    setIds(
                      event.target.checked
                        ? [...ids, action.id]
                        : ids.filter((id) => id !== action.id),
                    )
                  }
                />
                <span>
                  <strong className="text-sm">{action.title}</strong>
                  <span className="mt-1 block text-sm text-[color:var(--text-secondary)]">
                    {action.description}
                  </span>
                </span>
              </label>
              <Button
                className="mt-3"
                variant="outline"
                loading={busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await api.request(`/v1/actions/${action.id}/apply`, {
                      method: "POST",
                    });
                    onApplied();
                  } catch (error) {
                    setError(message(error));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Применить к плану
              </Button>
            </div>
          ))}
        </>
      )}
      {ids.length > 0 && simulated.data && (
        <>
          <CashflowForecastChart
            days={chartDays(forecast, simulated.data)}
            showBounds
          />
          <RiskCard
            risk={
              simulated.data.gaps[0] ? riskView(simulated.data.gaps[0]) : null
            }
            status={simulated.data.gaps.length ? "unknown" : "clear"}
          />
        </>
      )}
    </SectionCard>
  );
}
