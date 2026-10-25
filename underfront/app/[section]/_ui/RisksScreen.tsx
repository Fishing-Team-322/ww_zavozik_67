"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, ArrowRight } from "lucide-react";
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
import { chartDays, displayDate, rubles, forecastReliability, riskProbabilityText, gapAmount } from "@/src/entities/forecast";
import { CashflowWaterfall } from "@/src/features/cash-gap-inspector/ui/CashflowWaterfall";
import { FinanceState, ForecastNotice } from "./FinanceState";

const sourceLabels: Record<string, string> = { manual: "Добавлено вручную", recurring: "Регулярный платёж", invoice: "Счёт", onec_odata: "1С", gsheets: "Google Sheets" };
const riskEstimate = riskProbabilityText;

export function RisksScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const query = useSearchParams();
  const horizon = ["30", "60", "90"].includes(query.get("horizon") ?? "") ? query.get("horizon")! : "30";
  const forecast = useApiResource<Forecast>(`${base}/forecast?horizon=${horizon}`);
  const [chosen, setChosen] = useState<string | null>(null);
  const gaps = forecast.data?.gaps ?? [];
  const selected = gaps.find(gap => gap.id === (chosen ?? query.get("gap"))) ?? gaps[0];
  return <div className="space-y-5">
    <ContentHeading level={1}>Нехватка денег</ContentHeading>
    <FinanceState loading={forecast.loading} error={forecast.error} retry={forecast.refresh} />
    {forecast.data && <ContentText variant="description" tone="muted">Прогноз на {displayDate(forecast.data.as_of)} · горизонт {forecast.data.horizon} дней</ContentText>}
    {forecast.data && <ForecastNotice forecast={forecast.data} />}
    {forecast.data && gaps.length === 0 && <RiskCard risk={null} status={forecastReliability(forecast.data).spendingAvailable ? "clear" : "limited"} compact />}
    {forecast.data && gaps.length > 1 && <div className="flex flex-wrap gap-2" aria-label="Даты нехватки денег">{gaps.map(gap => <Button key={gap.id} variant={gap.id === selected?.id ? "default" : "outline"} size="sm" onClick={() => setChosen(gap.id)}>{displayDate(gap.date)}</Button>)}</div>}
    {selected && forecast.data && <GapDetails key={selected.id} base={base} horizon={horizon} gap={selected} forecast={forecast.data} onApplied={forecast.refresh} />}
  </div>;
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
  const events = useApiResource<Schemas["PlannedEvent"][]>(`${base}/events`);
  const [confirmAction, setConfirmAction] = useState<Schemas["Action"] | null>(null);
  const [notice, setNotice] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [simulationIds, setSimulationIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const simulated = useApiResource<Schemas["GapSimulation"]>(
    simulationIds.length ? `${base}/gaps/${encodeURIComponent(gap.id)}/simulate?horizon=${horizon}` : null,
    { method: "POST", json: { action_ids: simulationIds } },
  );
  const actions = [...new Map((detail.data?.actions ?? []).map(action => [`${action.kind}:${String(action.refs?.event_id ?? action.id)}`, action])).values()];
  const simulatedGap = simulated.data?.gaps.find(item => item.id === gap.id) ?? simulated.data?.gaps[0];
  const effectVisible = simulationIds.length > 0 && ids.length === simulationIds.length && ids.every(id => simulationIds.includes(id));
  const explanationDate = detail.data?.explanation?.date ?? detail.data?.worst_date ?? gap.explanation?.date ?? gap.worst_date;
  const actionTitle = (action: Schemas["Action"]) => {
    if (action.kind !== "shift_supplier_payment") return action.title;
    const event = events.data?.find(item => item.id === action.refs?.event_id);
    return event ? `Перенести «${event.title}» на 14 дней` : `${action.title} на 14 дней`;
  };

  const amount = gapAmount(gap);
  const actionEffect = (action: Schemas["Action"]) => action.effect.closes_gap ? "Риск на выбранном горизонте устранён" : `Нехватка после действия: ${rubles(action.effect.new_shortfall > 0 ? action.effect.new_shortfall : action.effect.new_shortfall_p90 ?? 0)}${action.effect.new_gap_date ? ` · с ${displayDate(action.effect.new_gap_date)}` : ""}`;
  const actionTerms = (action: Schemas["Action"]) => `${action.amount != null ? `${rubles(action.amount)} · ` : ""}${action.date ? `плановая дата ${displayDate(action.date)}. ` : ""}${action.cost_known === false ? "Стоимость и условия необходимо согласовать. " : ""}`;
  return <div className="space-y-5">
    <SectionCard className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-[color:var(--danger)]"><AlertTriangle size={18} aria-hidden="true" />Возможна нехватка денег</div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div><ContentText variant="meta" tone="muted">Когда</ContentText><strong className="mt-1 block text-lg font-semibold">{displayDate(gap.date)}</strong></div>
        <div><ContentText variant="meta" tone="muted">{amount.label}</ContentText><strong className="mt-1 block text-lg font-semibold tabular-nums text-[color:var(--danger)]">{amount.amount == null ? "Нет оценки" : rubles(amount.amount)}</strong></div>
        <div><ContentText variant="meta" tone="muted">Оценка риска</ContentText><strong className="mt-1 block text-sm font-medium">{riskEstimate(gap, forecast)}</strong></div>
        <div><ContentText variant="meta" tone="muted">До проблемы</ContentText><strong className="mt-1 block text-lg font-semibold">{gap.days_left < 0 ? "Уже наступила" : gap.days_left === 0 ? "Сегодня" : `${gap.days_left} дн.`}</strong></div>
      </div>
      <ContentText variant="description" tone="muted">По текущему плану к {displayDate(gap.date)} денег может не хватить на запланированные платежи. Это прогноз, а не уже совершённое списание.</ContentText>
    </SectionCard>
    {notice && <ContentText variant="description" role="status">{notice}</ContentText>}
    <FinanceState loading={detail.loading} error={detail.error || events.error || error} retry={() => { detail.refresh(); events.refresh(); }} />
    <div className="grid items-start gap-5 lg:grid-cols-2">
      <section className="min-w-0 space-y-3"><div><ContentHeading level={2}>Почему не хватает денег</ContentHeading><ContentText variant="description" tone="muted">{explanationDate ? `Состав остатка к ${displayDate(explanationDate)} — дню минимального прогнозного остатка после начала риска. Первая возможная нехватка: ${displayDate(gap.date)}.` : "Поступления, расходы и резерв по данным прогноза. Дата объяснения пока недоступна."}</ContentText></div>
        {detail.data && detail.data.causes.length > 0 ? <SectionCard className="space-y-4">
          <CashflowWaterfall contributions height={Math.max(180, detail.data.causes.length * 36)} steps={detail.data.causes.map((cause, index) => ({ id: `${cause.component_key}:${index}`, title: cause.title, amount: cause.amount, before: 0, after: cause.amount, kind: cause.amount >= 0 ? "income" : "expense" }))} />
          <div className="divide-y divide-[color:var(--border)]">{detail.data.causes.map((cause, index) => { const event = events.data?.find(item => item.id === cause.items_ref); return <div key={`${cause.component_key}:${index}`} className="flex flex-wrap items-start justify-between gap-2 py-3 text-sm"><div className="min-w-0"><strong className="block font-medium">{cause.title}</strong><span className="text-xs text-[color:var(--text-secondary)]">{event?.counterparty.name || "Контрагент не указан"} · {event?.date ? displayDate(event.date) : "Дата не указана"} · {event ? sourceLabels[event.source] ?? event.source : "Источник не указан"}</span>{cause.items_ref && <Link href={`/calendar?event=${encodeURIComponent(cause.items_ref)}`} className="mt-1 block text-xs text-[color:var(--accent)] underline">Открыть событие</Link>}</div><strong className="shrink-0 font-medium tabular-nums">{rubles(cause.amount)}</strong></div>; })}</div>
        </SectionCard> : !detail.loading && <ContentText variant="description" tone="muted">Отдельные события не выделены. Прогноз также учитывает общий поток поступлений и расходов.</ContentText>}
      </section>
      <section className="min-w-0 space-y-3"><div><ContentHeading level={2}>Что можно сделать</ContentHeading><ContentText variant="description" tone="muted">Выберите действия и посмотрите их совместный эффект.</ContentText></div>
        {actions.length > 0 ? <SectionCard className="divide-y divide-[color:var(--border)]">{actions.map(action => { const event = events.data?.find(item => item.id === action.refs?.event_id); return <div key={action.id} className="py-3 first:pt-0 last:pb-0"><Checkbox className="items-start" checked={ids.includes(action.id)} onChange={change => { setIds(current => change.target.checked ? [...current, action.id] : current.filter(id => id !== action.id)); setSimulationIds([]); }} label={<span className="min-w-0"><strong className="block text-sm font-medium text-[color:var(--text-primary)]">{actionTitle(action)}</strong><span className="mt-1 block text-xs text-[color:var(--text-secondary)]">{event ? `${event.counterparty.name || "Контрагент не указан"} · ${displayDate(event.date)} · ${rubles(event.amount)}` : `${actionTerms(action)}${action.description}`}</span>{event && <span className="mt-1 block text-xs text-[color:var(--text-secondary)]">{action.description}</span>}<span className="mt-1 block text-xs text-[color:var(--text-secondary)]">{actionEffect(action)}{action.cost > 0 ? ` · стоимость: ${rubles(action.cost)}` : ""}</span></span>} /><Button variant="ghost" size="sm" className="mt-2" disabled={busy} onClick={() => { setError(null); setConfirmAction(action); }}>Применить к плану</Button>{action.draft_message && <details className="mt-1 text-xs text-[color:var(--text-secondary)]"><summary className="cursor-pointer">Черновик сообщения</summary><p className="mt-2 whitespace-pre-wrap">{action.draft_message}</p></details>}</div>; })}</SectionCard> : !detail.loading && <ContentText variant="description" tone="muted">Подходящих действий пока нет. Проверьте ближайшие платежи в календаре.</ContentText>}
      </section>
    </div>
    {actions.length > 0 && <SectionCard className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><ContentHeading level={2}>Как изменится прогноз</ContentHeading><ContentText variant="description" tone="muted">Просмотр эффекта не меняет план и не отправляет сообщения.</ContentText></div><Button disabled={!ids.length || busy} onClick={() => setSimulationIds([...ids])}>Посмотреть эффект</Button></div>
      {!ids.length && <ContentText variant="description" tone="muted">Выберите одно или несколько действий справа.</ContentText>}
      {ids.length > 0 && !effectVisible && <ContentText variant="description" tone="muted">Нажмите «Посмотреть эффект», чтобы сравнить варианты.</ContentText>}
      {effectVisible && <FinanceState loading={simulated.loading} error={simulated.error} retry={simulated.refresh} />}
      {effectVisible && simulated.data && <><div className="flex flex-wrap items-center gap-4 text-sm"><div><ContentText variant="meta" tone="muted">Нехватка до изменений</ContentText><strong className="tabular-nums">{amount.amount == null ? "Нет оценки" : rubles(amount.amount)}</strong></div><ArrowRight size={17} aria-hidden="true" className="text-[color:var(--text-secondary)]" /><div><ContentText variant="meta" tone="muted">Нехватка после изменений</ContentText><strong className={`tabular-nums ${simulated.data.gaps.length === 0 ? "text-[color:var(--success)]" : "text-[color:var(--danger)]"}`}>{simulatedGap ? gapAmount(simulatedGap).amount == null ? "Нет оценки" : rubles(gapAmount(simulatedGap).amount!) : "Риск устранён"}</strong></div><span className="text-xs text-[color:var(--text-secondary)]">{simulated.data.gaps.length === 0 ? "Нехватка устранена" : `Риск с ${simulatedGap ? displayDate(simulatedGap.date) : "неизвестной даты"}. ${simulatedGap ? riskEstimate(simulatedGap, forecast) : "Оценка недоступна"}`}</span></div><CashflowForecastChart days={chartDays(forecast, simulated.data)} height={220} compactDates showBounds={false} showDeficitDots={false} showScenarioDelta scenarioLabel="После действий" firstGapDate={gap.date} /></>}
      <ContentText variant="description" tone="muted">Применение каждого действия к плану подтверждается отдельно. Система не переводит деньги, не оформляет кредит и не отправляет письма.</ContentText>
    </SectionCard>}
    <ConfirmDialog open={!!confirmAction} title="Применить действие к плану?" description={confirmAction ? `${actionTitle(confirmAction)}. ${actionTerms(confirmAction)}${confirmAction.description}. ${actionEffect(confirmAction)}. Изменится только план в «ПУЛЬС»: реальные платежи и переписка не изменятся.` : undefined} loading={busy} onCancel={() => { if (!busy) setConfirmAction(null); }} onConfirm={async () => { if (!confirmAction) return; setBusy(true); setError(null); try { await api.request(`/v1/actions/${confirmAction.id}/apply`, { method: "POST" }); setConfirmAction(null); setIds([]); setSimulationIds([]); setNotice("План обновлён."); detail.refresh(); events.refresh(); onApplied(); } catch (cause) { setError(message(cause)); } finally { setBusy(false); } }}>{error && <p role="alert">{error}</p>}</ConfirmDialog>
  </div>;
}
