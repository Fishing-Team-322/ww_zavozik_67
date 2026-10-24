"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, RotateCcw, X } from "lucide-react";
import { formatGapDate, type CashGapDetails, type CashGapInspectorStatus, type GapSimulation } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { Button } from "@/src/shared/ui/button";
import { Dialog } from "@/src/shared/ui/dialog";
import { Skeleton } from "@/src/shared/ui/skeleton";
import { CashGapSummary } from "./CashGapSummary";
import { CashflowWaterfall } from "./CashflowWaterfall";
import { CashGapCausesTable } from "./CashGapCausesTable";
import { CashGapActions } from "./CashGapActions";
import { CashGapComparisonChart } from "./CashGapComparisonChart";
import { gapHeading, gapMuted, gapPanel, sourceLabels } from "./styles";

export interface CashGapInspectorProps {
  data: CashGapDetails | null;
  simulation: GapSimulation | null;
  status: CashGapInspectorStatus;
  selectedActionIds: readonly string[];
  error?: string | null;
  onToggleAction: (id: string) => void;
  onReset: () => void;
  onSaveScenario: () => void;
  onRetry: () => void;
}

export function CashGapInspector({ data, simulation, status, selectedActionIds, error, onToggleAction, onReset, onSaveScenario, onRetry }: CashGapInspectorProps) {
  const [eventId, setEventId] = useState<string | null>(null);
  if (status === "loading") return <div role="status" aria-label="Загрузка анализа кассового разрыва" className="space-y-4"><Skeleton className="h-28 !rounded-[5px]" /><div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-64 !rounded-[5px]" /><Skeleton className="h-64 !rounded-[5px]" /></div><span className="sr-only">Загрузка анализа</span></div>;
  if (status === "empty" || (status !== "error" && (!data || !simulation))) return <div className={`${gapPanel} flex flex-wrap items-center gap-3 p-4`}><CheckCircle2 size={18} className="text-[color:var(--nav-item-icon)]" /><div className="min-w-0 flex-1"><p className="text-[13px] font-medium">Нет данных о кассовом разрыве</p><p className={gapMuted}>Загрузите другой расчёт или обновите данные.</p></div><Button variant="outline" size="lg" onClick={onRetry}>Обновить</Button></div>;
  if (!data || !simulation) return <div role="alert" className={`${gapPanel} p-4`}><p className="text-[13px] font-medium">Не удалось получить расчёт</p><p className={`mt-1 ${gapMuted}`}>{error ?? "Повторите запрос."}</p><Button variant="outline" size="lg" className="mt-3" onClick={onRetry}>Повторить</Button></div>;

  const { baseline, alternative } = simulation;
  const busy = status === "simulating";
  const hasChanges = simulation.actionIds.length > 0;
  const event = data.scenario.events.find((item) => item.id === eventId);
  const eventVariants = event ? simulation.events.filter((item) => item.id === event.id || item.id.startsWith(`${event.id}:part-`)) : [];
  const comparisonRows = [
    { title: "Минимальный остаток", before: formatRub(baseline.minimum), after: formatRub(alternative.minimum), negative: alternative.minimum < 0 },
    { title: "Максимальная нехватка", before: formatRub(baseline.maximumShortfall), after: formatRub(alternative.maximumShortfall), negative: alternative.maximumShortfall > 0 },
    { title: "Дней с нехваткой", before: String(baseline.shortfallDays), after: String(alternative.shortfallDays) },
    { title: "Дата первого разрыва", before: baseline.firstGapDate ? formatGapDate(baseline.firstGapDate) : "Нет разрыва", after: alternative.firstGapDate ? formatGapDate(alternative.firstGapDate) : "Нет разрыва" },
    { title: data.probabilitySource === "mock" ? "Вероятность · mock" : "Вероятность модели", before: data.probability === null ? "Нет оценки" : `${data.probability}%`, after: simulation.alternativeProbability === null ? "Нет оценки" : `${simulation.alternativeProbability}%` },
  ];

  return <div className="min-w-0 space-y-4 text-[13px] leading-5 text-[color:var(--nav-item-active-text)]" aria-busy={busy}>
    {status === "error" ? <div role="alert" className="flex flex-wrap items-center gap-3 rounded-[5px] border border-[color:var(--border)] px-4 py-3"><AlertCircle size={16} className="shrink-0 text-[color:var(--warning)]" /><p className="min-w-0 flex-1 text-[12px]">{error} Показан последний успешный расчёт.</p><Button variant="outline" size="lg" onClick={onRetry}>Повторить</Button></div> : null}
    <CashGapSummary forecast={alternative} asOf={data.scenario.asOf} probability={simulation.alternativeProbability} probabilitySource={data.probabilitySource} scenarioLabel={hasChanges ? "После выбранных действий" : "Базовый прогноз"} />

    <section className={gapPanel} aria-label="Причины кассового разрыва">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--border)] px-4 py-3"><div><h3 className={gapHeading}>Почему возникла нехватка денег?</h3><p className={`mt-1 ${gapMuted}`}>Базовый сценарий{baseline.firstGapDate ? ` до ${formatGapDate(baseline.firstGapDate)}` : ""}. Каждая операция меняет остаток.</p></div><span className={`${gapMuted} tabular-nums`}>{formatRub(data.scenario.openingBalance)} → {formatRub(simulation.waterfall[simulation.waterfall.length - 1]?.after ?? data.scenario.openingBalance)}</span></header>
      <div className="px-3 pt-3"><CashflowWaterfall steps={simulation.waterfall} /></div>
      <p className={`px-4 pb-3 ${gapMuted}`}>{data.scenario.openingSource}. Нажмите на событие, чтобы открыть источник и детали.</p>
      <CashGapCausesTable steps={simulation.waterfall} onOpenEvent={setEventId} />
    </section>

    <div className="grid min-w-0 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className={gapPanel} aria-label="Действия для предотвращения кассового разрыва">
        <header className="border-b border-[color:var(--border)] px-4 py-3"><h3 className={gapHeading}>Как избежать нехватки денег</h3><p className={`mt-1 ${gapMuted}`}>У каждой меры показан её самостоятельный эффект. Комбинация — в сравнении.</p></header>
        <CashGapActions actions={data.actions} previews={simulation.actionPreviews} selectedActionIds={selectedActionIds} disabled={busy} onToggle={onToggleAction} />
      </section>

      <section className={gapPanel} aria-label="Сравнение сценариев до и после">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border)] px-4 py-3"><h3 className={gapHeading}>До / После</h3><span role="status" aria-live="polite" className={`${gapMuted} tabular-nums`}>{busy ? "Пересчёт сценария…" : `Выбрано действий: ${simulation.actionIds.length}`}</span></header>
        <div className="px-4 py-3">
          <p className={gapMuted}>Нехватка после изменений</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1"><p className={`text-[24px] font-semibold leading-7 tabular-nums ${alternative.maximumShortfall ? "text-[color:var(--danger)]" : "text-[color:var(--accent)]"}`}>{formatRub(alternative.maximumShortfall)}</p><p className={`text-[12px] ${alternative.maximumShortfall ? "text-[color:var(--nav-item-text)]" : "text-[color:var(--accent)]"}`}>{!hasChanges ? "Исходный сценарий" : alternative.maximumShortfall === 0 ? "Разрыв устранён в выбранном периоде" : alternative.maximumShortfall < baseline.maximumShortfall ? "Нехватка уменьшилась" : "Разрыв сохраняется"}</p></div>
          <div className={`mt-3 flex flex-wrap gap-x-4 gap-y-1 ${gapMuted}`}><span className="inline-flex items-center gap-2"><i className="w-4 border-t border-dashed border-[color:var(--nav-item-icon)]" />До</span><span className="inline-flex items-center gap-2"><i className="w-4 border-t-2 border-[color:var(--accent)]" />После</span><span>Затенение — дни нехватки</span></div>
        </div>
        <div className="px-2"><CashGapComparisonChart baseline={baseline} alternative={alternative} /></div>
        <div className="overflow-x-auto"><table className="w-full min-w-[320px] border-collapse text-[12px] leading-4"><thead className="bg-[color:var(--sidebar-bg)] text-[color:var(--nav-item-text)]"><tr><th scope="col" className="px-4 py-2 text-left font-medium">Показатель</th><th scope="col" className="px-4 py-2 text-right font-medium">До</th><th scope="col" className="px-4 py-2 text-right font-medium">После</th></tr></thead><tbody>{comparisonRows.map((row) => <tr key={row.title} className="border-t border-[color:var(--border-muted)]"><th scope="row" className="px-4 py-2 text-left font-normal">{row.title}</th><td className="whitespace-nowrap px-4 py-2 text-right tabular-nums text-[color:var(--nav-item-text)]">{row.before}</td><td className={`whitespace-nowrap px-4 py-2 text-right font-medium tabular-nums ${row.negative ? "text-[color:var(--danger)]" : ""}`}>{row.after}</td></tr>)}</tbody></table></div>
        <div className="space-y-3 border-t border-[color:var(--border)] px-4 py-3">
          <p className={`${gapMuted} tabular-nums`}>Стоимость действий: {formatRub(simulation.totalCost)} · Остаток на {formatGapDate(data.scenario.endDate)}: {formatRub(alternative.closing)}.</p>
          <p className={gapMuted}>Отсрочки, комиссии и возврат финансирования учтены до конца периода. Вероятность альтернативы не рассчитывается на фронтенде.</p>
          <div className="flex flex-wrap gap-2"><Button variant="outline" size="lg" disabled={busy || !selectedActionIds.length} onClick={onReset}><RotateCcw aria-hidden="true" />Сбросить изменения</Button><Button size="lg" disabled={status !== "ready" || !hasChanges} onClick={onSaveScenario}>Сохранить как сценарий</Button></div>
        </div>
      </section>
    </div>

    <Dialog open={Boolean(event)} onClose={() => setEventId(null)} title={event?.title} description="Событие базового финансового прогноза" className="!fixed inset-y-0 right-0 !h-dvh !max-h-dvh max-w-[420px] !rounded-none !shadow-none" headerActions={<Button variant="ghost" size="icon" aria-label="Закрыть подробности" onClick={() => setEventId(null)}><X /></Button>}>
      {event ? <div className="space-y-4 text-[13px] text-[color:var(--nav-item-active-text)]">
        <p className={`text-[24px] font-semibold leading-7 tabular-nums ${event.amount > 0 ? "text-[color:var(--accent)]" : ""}`}>{event.amount > 0 ? "+" : ""}{formatRub(event.amount)}</p>
        <dl className="divide-y divide-[color:var(--border-muted)]">{[["Контрагент", event.counterparty], ["Дата", formatGapDate(event.date, true)], ["Направление", event.amount > 0 ? "Поступление" : "Списание"], ["Источник", sourceLabels[event.source]], ["Документ", event.document]].map(([label, value]) => <div key={label} className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-2"><dt className={gapMuted}>{label}</dt><dd className="break-words">{value}</dd></div>)}</dl>
        {event.note ? <p className={gapMuted}>{event.note}</p> : null}
        {hasChanges ? <div className="border-t border-[color:var(--border)] pt-3"><h4 className="font-medium">В текущей симуляции</h4>{eventVariants.map((variant) => <p key={variant.id} className="mt-2 flex justify-between gap-3 text-[12px] tabular-nums"><span>{formatGapDate(variant.date)}</span><span>{formatRub(variant.amount)}</span></p>)}</div> : null}
        <Button variant="outline" size="lg" onClick={() => setEventId(null)}>Закрыть</Button>
      </div> : null}
    </Dialog>
  </div>;
}
