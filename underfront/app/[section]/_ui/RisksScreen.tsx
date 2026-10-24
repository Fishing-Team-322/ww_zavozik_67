"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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
import { Button, ConfirmDialog, Checkbox } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { RiskCard, CashflowForecastChart } from "@/src/widgets/finance-panels";
import { chartDays, riskView, rubles } from "@/src/entities/forecast";
import { CashflowWaterfall } from "@/src/features/cash-gap-inspector/ui/CashflowWaterfall";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function RisksScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const query = useSearchParams();
  const horizon = ["30", "60", "90"].includes(query.get("horizon") ?? "") ? query.get("horizon")! : "30";
  const forecast = useApiResource<Forecast>(`${base}/forecast?horizon=${horizon}`);
  const [chosen, setSelected] = useState<string | null>(null);
  const selected = chosen ?? query.get("gap");
  return (
    <>
      <ContentHeading level={1} className="mb-6">Риски</ContentHeading>
      <FinanceState
        loading={forecast.loading}
        error={forecast.error}
        retry={forecast.refresh}
      />
      <ForecastNotice forecast={forecast.data} />
      {forecast.data?.gaps.length === 0 && (
        <RiskCard risk={null} status="clear" />
      )}
      {selected && forecast.data && !forecast.data.gaps.some(gap => gap.id === selected) && <ContentText variant="body" role="status" className="my-3">Этот разрыв больше не найден в текущем прогнозе. Выберите актуальный риск ниже.</ContentText>}
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
            horizon={horizon}
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
  horizon,
  gap,
  forecast,
  onApplied,
}: {
  base: string;
  horizon: string;
  gap: Gap;
  forecast: Forecast;
  onApplied: () => void;
}) {
  const detail = useApiResource<Schemas["GapDetail"]>(
    `${base}/gaps/${encodeURIComponent(gap.id)}?horizon=${horizon}`,
  );
  const [confirmAction, setConfirmAction] = useState<Schemas["Action"] | null>(null);
  const [notice, setNotice] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const simulated = useApiResource<Schemas["GapSimulation"]>(
    ids.length ? `${base}/gaps/${encodeURIComponent(gap.id)}/simulate?horizon=${horizon}` : null,
    { method: "POST", json: { action_ids: ids } },
  );
  return (
    <SectionCard className="mt-5 space-y-4">
      <ContentHeading level={2} >Что влияет на разрыв · {gap.date}</ContentHeading>
      {forecast.points.length > 0 && <ContentText variant="body" >Минимальный остаток за период: {rubles(Math.min(...forecast.points.map(point => point.p50)))}</ContentText>}
      <ContentText variant="body" >Изменения относятся только к плану: кредит не оформляется, сообщения контрагентам не отправляются.</ContentText>
      {notice && <p role="status">{notice}</p>}
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
          <CashflowWaterfall contributions steps={detail.data.causes.map((cause, i) => ({ id: `${cause.component_key}:${i}`, title: cause.title, amount: cause.amount, before: 0, after: cause.amount, kind: cause.amount >= 0 ? "income" : "expense" }))} />
          <ul className="list-inside list-disc space-y-2 text-sm">
            {detail.data.causes.map((cause) => (
              <li key={cause.component_key}>
                {cause.title}: {rubles(cause.amount)}{cause.items_ref && <Link className="ml-2 text-[color:var(--accent)] underline" href={`/calendar?event=${encodeURIComponent(cause.items_ref)}`}>Событие и источник</Link>}
              </li>
            ))}
          </ul>
          <ContentText variant="description" tone="muted" >
            Также учитывается ожидаемый поток бизнеса по модели. Выберите
            действия, чтобы проверить их эффект.
          </ContentText>
          {detail.data.actions.map((action) => (
            <div
              key={action.id}
              className="rounded-lg border border-[color:var(--border)] p-4"
            >
              <label className="flex items-start gap-3">
                <Checkbox
                  aria-label={action.title}
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
                onClick={() => { setError(null); setConfirmAction(action); }}
              >
                Применить к плану
              </Button>
              <ContentText variant="meta" className="mt-2">Стоимость: {rubles(action.cost)} · ожидаемая нехватка после действия: {rubles(action.effect.new_shortfall)}</ContentText>
              {action.draft_message && <ContentText variant="body" className="mt-2 whitespace-pre-wrap">Черновик сообщения: {action.draft_message}</ContentText>}
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
      <ConfirmDialog open={!!confirmAction} title="Применить действие к плану?" description={confirmAction?.description} loading={busy} onCancel={() => { if (!busy) setConfirmAction(null); }} onConfirm={async () => { if (!confirmAction) return; setBusy(true); setError(null); try { await api.request(`/v1/actions/${confirmAction.id}/apply`, { method: "POST" }); setConfirmAction(null); setIds([]); setNotice("План обновлён."); onApplied(); } catch (cause) { setError(message(cause)); } finally { setBusy(false); } }}>{error && <p role="alert">{error}</p>}</ConfirmDialog>
    </SectionCard>
  );
}
