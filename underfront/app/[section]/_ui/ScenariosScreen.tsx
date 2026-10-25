"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import Link from "next/link";
import { useState } from "react";
import { ArrowRightLeft, CalendarClock, CircleHelp, ReceiptText, SlidersHorizontal, TrendingDown, Wallet } from "lucide-react";
import { useSession } from "@/src/features/auth";
import {
  api,
  message,
  type Forecast,
  type Schemas,
  type PlannedEvent,
} from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select, ConfirmDialog, Dialog } from "@/src/shared/ui";
import {
  CashflowForecastChart,
  DEFAULT_SCENARIO,
  ScenarioControls,
  type ScenarioParams,
} from "@/src/widgets/finance-panels";
import { chartDays, displayDate, fallbackNotice, forecastReliability, riskProbabilityText, gapAmount } from "@/src/entities/forecast";
import { money } from "./finance-utils";
import { FinanceState, ForecastNotice } from "./FinanceState";
import { scenarioWindowBounds, shiftScenarioDate } from "@/src/entities/forecast/model/scenario-window";

const presetIcons = {
  delay_counterparty: CalendarClock,
  scale_revenue: TrendingDown,
  add_expense: ReceiptText,
  scale_fixed_costs: Wallet,
  move_event: ArrowRightLeft,
};
type ReadyCondition = "delay_counterparty" | "scale_revenue" | "add_expense" | "scale_fixed_costs";
const readyConditions: Array<{ kind: ReadyCondition; label: string }> = [
  { kind: "delay_counterparty", label: "Задержка оплаты" },
  { kind: "scale_revenue", label: "Падение выручки" },
  { kind: "add_expense", label: "Внеплановый расход" },
  { kind: "scale_fixed_costs", label: "Постоянные расходы" },
];

export function ScenariosScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const forecast = useApiResource<Forecast>(`${base}/forecast?horizon=90`);
  const [selectedStart, setSelectedStart] = useState("");
  const window = scenarioWindowBounds(forecast.data?.points[0]?.date ?? "", forecast.data?.points.at(-1)?.date ?? "", selectedStart);
  const periodQuery = new URLSearchParams({ from: window.from, to: window.to });
  const events = useApiResource<PlannedEvent[]>(`${base}/events`);
  const [params, setParams] = useState<ScenarioParams>(DEFAULT_SCENARIO);
  const [counterparty, setCounterparty] = useState("");
  const [date, setDate] = useState("");
  const effectiveExpenseDate = date || window.from;
  const [title, setTitle] = useState("Мой сценарий");
  const scenarios = useApiResource<Schemas["Scenario"][]>(`${base}/scenarios`);
  const presets = useApiResource<Array<{ kind: Schemas["ScenarioStep"]["kind"]; title: string }>>("/v1/scenario-presets");
  const [selectedId, setSelectedId] = useState("");
  const [customSteps, setCustomSteps] = useState<Schemas["ScenarioStep"][] | null>(null);
  const [selectedCondition, setSelectedCondition] = useState<ReadyCondition | null>(null);
  const [dirty, setDirty] = useState(false);
  const [fixedIncrease, setFixedIncrease] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sliderSteps: Schemas["ScenarioStep"][] = [];
  if (selectedCondition === "scale_revenue" && params.revenueDropPercent)
    sliderSteps.push({
      kind: "scale_revenue",
      factor: 1 - params.revenueDropPercent / 100,
    });
  if (selectedCondition === "add_expense" && params.unexpectedExpense && forecast.data)
    sliderSteps.push({
      kind: "add_expense",
      amount: params.unexpectedExpense,
      date: effectiveExpenseDate,
    });
  if (selectedCondition === "delay_counterparty" && params.paymentDelayDays && counterparty)
    sliderSteps.push({
      kind: "delay_counterparty",
      counterparty_id: counterparty,
      delay_days: params.paymentDelayDays,
    });
  if (selectedCondition === "scale_fixed_costs" && fixedIncrease) sliderSteps.push({ kind: "scale_fixed_costs", factor: 1 + fixedIncrease / 100 });
  const steps = customSteps ?? sliderSteps;
  const missingClient = customSteps === null && selectedCondition === "delay_counterparty" && params.paymentDelayDays > 0 && !counterparty;
  const savedCompare = useApiResource<Schemas["ScenarioComparison"]>(selectedId && !dirty && window.valid ? `/v1/scenarios/${selectedId}/compare?${periodQuery}` : null);
  const compare = useApiResource<Schemas["ScenarioComparison"]>(
    forecast.data && window.valid && !missingClient && (!selectedId || dirty)
      ? `${base}/scenarios/preview?${periodQuery}`
      : null,
    { method: "POST", json: { steps: steps.length ? steps : [{ kind: "scale_revenue", factor: 1 }] } },
  );
  const clients = [
    ...new Map(
      (events.data || [])
        .filter(
          (event) =>
            event.direction === "in" &&
            event.status === "expected" &&
            event.date > (forecast.data?.as_of || "") &&
            event.counterparty.id,
        )
        .map((event) => [
          event.counterparty.id!,
          { value: event.counterparty.id!, label: event.counterparty.name },
        ]),
    ).values(),
  ];
  const comparison = selectedId && !dirty ? savedCompare : compare;
  const recalculating = comparison.loading && !missingClient;
  const result = steps.length ? comparison.data?.scenario : undefined;
  const baseForecast = comparison.data?.base;
  const baseGap = baseForecast?.gaps[0];
  const scenarioGap = result?.gaps[0];
  const baseMinimum = baseForecast?.points.reduce<Forecast["points"][number] | null>((minimum, point) => !minimum || point.p50 < minimum.p50 ? point : minimum, null);
  const scenarioMinimum = result?.points.reduce<Forecast["points"][number] | null>((minimum, point) => !minimum || point.p50 < minimum.p50 ? point : minimum, null);
  const minimumChange = baseMinimum && scenarioMinimum ? scenarioMinimum.p50 - baseMinimum.p50 : null;
  const reserve = company!.reserve;
  const limitedProbability = Boolean(baseForecast && !forecastReliability(baseForecast).probabilityAvailable || result && !forecastReliability(result).probabilityAvailable);
  const modelNotice = baseForecast?.fallback_used ? fallbackNotice(baseForecast.warnings) : baseForecast?.low_confidence ? "Надёжность оценки ограничена полнотой истории." : "Прогноз построен по доступным финансовым данным.";
  const chartPoints = baseForecast ? chartDays(baseForecast, result).filter(day => day.date >= window.from && day.date <= window.to) : [];
  const gapChange = scenarioGap && baseGap
    ? scenarioGap.shortfall === baseGap.shortfall ? "Для первых дат нехватки сумма не изменилась." : `Для первых дат нехватки сумма ${scenarioGap.shortfall > baseGap.shortfall ? "увеличилась" : "уменьшилась"} на ${money(Math.abs(scenarioGap.shortfall - baseGap.shortfall))}.`
    : scenarioGap ? "В базовом плане предупреждения не было." : baseGap ? "По сценарию риск ниже порога предупреждения модели." : "Предупреждений о нехватке нет в обоих прогнозах.";

  function chooseCondition(kind: ReadyCondition) {
    setSelectedId(""); setCustomSteps(null); setSelectedCondition(kind);
    setParams({ paymentDelayDays: kind === "delay_counterparty" ? 7 : 0, revenueDropPercent: kind === "scale_revenue" ? 20 : 0, unexpectedExpense: kind === "add_expense" ? 25000 : 0 });
    setFixedIncrease(kind === "scale_fixed_costs" ? 10 : 0);
    setCounterparty(""); setDate(""); setTitle("Мой сценарий"); setDirty(true); setSaved(null);
  }

  function startCustomScenario() {
    setSelectedId(""); setSelectedCondition(null); setCustomSteps([]);
    setTitle("Мой сценарий"); setDirty(true); setSaved(null);
  }

  function addPreset(kind: Schemas["ScenarioStep"]["kind"]) {
    setCustomSteps(steps.some(step => step.kind === kind)
      ? steps.filter(step => step.kind !== kind)
      : [...steps, kind === "scale_revenue" ? { kind, factor: 0.8 } : kind === "scale_fixed_costs" ? { kind, factor: 1.1 } : kind === "delay_counterparty" ? { kind, delay_days: 7, counterparty_id: clients[0]?.value } : kind === "move_event" ? { kind, event_id: events.data?.find(event => event.editable)?.id, date: window.from } : { kind, amount: 0, date: window.from }]);
    setDirty(true);
    setSaved(null);
  }

  function resetScenario() {
    setSelectedId(""); setCustomSteps(null); setParams(DEFAULT_SCENARIO);
    setSelectedCondition(null);
    setCounterparty(""); setDate(""); setFixedIncrease(0);
    setTitle("Мой сценарий"); setDirty(false); setSaved(null);
  }
  async function saveScenario() {
    if (!title.trim() || !steps.length || missingClient || !comparison.data || comparison.loading) return;
    setSaving(true);
    setError(null);
    try {
      const stored = await api.request<Schemas["Scenario"]>(selectedId ? `/v1/scenarios/${selectedId}` : `${base}/scenarios`, {
        method: selectedId ? "PATCH" : "POST",
        json: { title, steps },
      });
      setSelectedId(stored.id); setCustomSteps(stored.steps); setSelectedCondition(null); setDirty(false);
      setSaved("Сценарий сохранён.");
      setSaveOpen(false);
      scenarios.refresh();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <ContentHeading level={1}>Сценарии</ContentHeading>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="lg" onClick={resetScenario}>Сбросить</Button>
          <Button
            size="lg"
            disabled={!steps.length || missingClient || !comparison.data || comparison.loading}
            onClick={() => { setError(null); setSaveOpen(true); }}
          >Сохранить</Button>
        </div>
      </div>
      <FinanceState
        loading={forecast.loading && !forecast.data}
        error={forecast.error || comparison.error || scenarios.error || presets.error || events.error || (saveOpen ? null : error)}
        retry={() => {
          forecast.refresh();
          compare.refresh(); savedCompare.refresh(); scenarios.refresh(); presets.refresh(); events.refresh();
        }}
      />
      <div className="mb-5 flex flex-wrap items-center gap-2" role="group" aria-label="Выбор условий">
        {readyConditions.map(condition => {
          const Icon = presetIcons[condition.kind];
          const active = customSteps === null && selectedCondition === condition.kind;
          return <button key={condition.kind} type="button" aria-pressed={active} onClick={() => chooseCondition(condition.kind)} className={`inline-flex min-h-10 items-center gap-2 rounded-[6px] border px-3 text-sm font-medium transition-colors hover:border-[color:var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] ${active ? "border-[color:var(--accent)] bg-[color:var(--surface-subtle)] text-[color:var(--text-primary)]" : "border-[color:var(--border)] text-[color:var(--text-secondary)]"}`}><Icon size={16} aria-hidden="true" />{condition.label}</button>;
        })}
        <button type="button" aria-pressed={customSteps !== null} onClick={startCustomScenario} className={`inline-flex min-h-10 items-center gap-2 rounded-[6px] border px-3 text-sm font-medium transition-colors hover:border-[color:var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] ${customSteps !== null ? "border-[color:var(--accent)] bg-[color:var(--surface-subtle)] text-[color:var(--text-primary)]" : "border-[color:var(--border)] text-[color:var(--text-secondary)]"}`}><SlidersHorizontal size={16} aria-hidden="true" />Свой сценарий</button>
      </div>
      <div className="grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-[320px_minmax(0,1fr)] lg:gap-7 xl:grid-cols-[340px_minmax(0,1fr)]">
        <section className="min-w-0 space-y-4 lg:border-r lg:border-[color:var(--border)] lg:pr-6" aria-label="Параметры сценария">
          <Select density="form" size="md" label="Сохранённый сценарий" value={selectedId} options={[{ value: "", label: "Новый сценарий" }, ...(scenarios.data ?? []).map(scenario => ({ value: scenario.id, label: scenario.title }))]} onChange={event => { const scenario = scenarios.data?.find(item => item.id === event.target.value); setSelectedId(scenario?.id ?? ""); setCustomSteps(scenario?.steps ?? null); setSelectedCondition(null); setTitle(scenario?.title ?? "Мой сценарий"); setDirty(false); setSaved(null); }} />
          <div className="border-t border-[color:var(--border)] pt-4">
            <ContentHeading level={2}>{customSteps ? "Комбинация условий" : selectedCondition ? readyConditions.find(item => item.kind === selectedCondition)?.label : "Настройка сценария"}</ContentHeading>
            {customSteps && <ContentText variant="description" className="mt-1">Добавляйте и настраивайте несколько условий вместе.</ContentText>}
            {!customSteps && !selectedCondition && <ContentText variant="description" className="mt-2">Выберите готовое условие выше или создайте свой сценарий.</ContentText>}
            {selectedCondition && customSteps === null && <div className="mt-4 space-y-4">
              {selectedCondition !== "scale_fixed_costs" && <ScenarioControls bare visibleKeys={[selectedCondition === "delay_counterparty" ? "paymentDelayDays" : selectedCondition === "scale_revenue" ? "revenueDropPercent" : "unexpectedExpense"]} value={params} onChange={value => { setParams(value); setDirty(true); setSaved(null); }} />}
              {selectedCondition === "delay_counterparty" && <><Select density="form" size="md" label="Клиент с плановым поступлением" placeholder="Выберите клиента" value={counterparty} onChange={event => { setCounterparty(event.target.value); setDirty(true); }} options={clients} />{missingClient && <ContentText variant="description">Выберите клиента, чтобы рассчитать задержку поступления.</ContentText>}</>}
              {selectedCondition === "add_expense" && <Input type="date" label="Дата расхода" min={forecast.data?.points[0]?.date} max={forecast.data?.points.at(-1)?.date} value={effectiveExpenseDate} onChange={event => { setDate(event.target.value); setDirty(true); }} />}
              {selectedCondition === "scale_fixed_costs" && <Input label="Рост постоянных расходов, %" type="number" min="0" max="900" value={fixedIncrease} onChange={event => { setFixedIncrease(Number(event.target.value)); setDirty(true); }} />}
            </div>}
            {customSteps && <div className="mt-3 space-y-3">
              {customSteps.length === 0 && <ContentText variant="description">Добавьте одно или несколько условий.</ContentText>}
              {customSteps.map((step, index) => <StepEditor key={index} step={step} clients={clients} events={events.data ?? []} onChange={value => { setCustomSteps(customSteps.map((item, stepIndex) => stepIndex === index ? value : item)); setDirty(true); setSaved(null); }} onRemove={() => { setCustomSteps(customSteps.filter((_, stepIndex) => stepIndex !== index)); setDirty(true); setSaved(null); }} />)}
              <div className="flex flex-wrap gap-2">{readyConditions.map(condition => <Button key={condition.kind} variant="outline" size="sm" disabled={customSteps.some(step => step.kind === condition.kind)} onClick={() => addPreset(condition.kind)}>+ {presets.data?.find(preset => preset.kind === condition.kind)?.title ?? condition.label}</Button>)}</div>
              <Button variant="ghost" size="sm" disabled={customSteps.some(step => step.kind === "move_event")} onClick={() => addPreset("move_event")}>+ Перенос события</Button>
            </div>}
          </div>
          {saved && <ContentText variant="description" role="status" tone="success">{saved}</ContentText>}
          {selectedId && !dirty && <Link className="block text-xs text-[color:var(--accent)] underline underline-offset-2" href={`/forecast?scenario=${encodeURIComponent(selectedId)}`}>Открыть прогноз по сценарию</Link>}
          {selectedId && <Button variant="ghost" size="sm" onClick={() => setDeleting(true)}>Удалить сценарий</Button>}
        </section>
        <section className="min-w-0" aria-label="Сравнение прогнозов">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <ContentHeading level={2}>Прогноз на 30 дней</ContentHeading>
            {baseForecast && <details className="relative text-xs text-[color:var(--text-secondary)]"><summary className="inline-flex cursor-pointer list-none items-center gap-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]"><CircleHelp size={14} aria-hidden="true" />{baseForecast.fallback_used ? "Упрощённый прогноз" : "О прогнозе"}</summary><p className="absolute right-0 top-full z-10 mt-2 w-64 border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-3 leading-5 shadow-[var(--shadow-md)]">{modelNotice}</p></details>}
          </div>
          <div className="my-4 grid gap-3 sm:grid-cols-2" role="group" aria-label="Период сравнения">
            <Input label="С даты" type="date" value={window.from} min={forecast.data?.points[0]?.date} max={window.latestStart} onChange={event => setSelectedStart(event.target.value)} />
            <Input label="По дату" type="date" value={window.to} min={window.earliestEnd} max={forecast.data?.points.at(-1)?.date} onChange={event => setSelectedStart(shiftScenarioDate(event.target.value, -29))} />
          </div>
          <ContentText variant="description" className="mb-3">Период — 30 календарных дней в пределах прогноза на 90 дней от последней выписки. Расчёт учитывает денежные потоки до начала выбранного периода.</ContentText>
          {forecast.data && !window.valid && <p role="alert" className="mb-3 text-sm text-[color:var(--danger)]">Выберите 30 дней внутри доступного прогноза.</p>}
          {baseForecast && <ForecastNotice forecast={baseForecast} />}
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[color:var(--text-secondary)]"><span className="inline-flex items-center gap-1.5"><i className="h-0.5 w-4 bg-[color:var(--accent)]" />Базовый прогноз</span><span className={`inline-flex items-center gap-1.5 ${result ? "" : "opacity-45"}`}><i className="w-4 border-t-2 border-dashed border-[color:var(--warning)]" />С изменениями</span><span className="inline-flex items-center gap-1.5"><i className="w-4 border-t border-dashed border-[color:var(--danger)]" />Нулевой остаток</span></div>
          <div className="relative" aria-busy={recalculating}>
            <CashflowForecastChart days={chartPoints} height={280} compactDates showScenario={Boolean(result)} scenarioLabel="С изменениями" hideSeries={recalculating} animate={false} showDeficitDots={false} showScenarioDelta firstGapDate={[baseGap?.date, scenarioGap?.date].filter((value): value is string => Boolean(value)).sort()[0]} />
            {recalculating && <div className="absolute inset-0 flex items-center justify-center"><span role="status" className="inline-flex items-center gap-2 border border-[color:var(--border)] bg-[color:var(--surface-elevated)] px-3 py-2 text-sm font-medium text-[color:var(--text-primary)] shadow-[var(--shadow-md)]"><span className="size-4 animate-spin rounded-full border-2 border-[color:var(--border)] border-t-[color:var(--accent)]" aria-hidden="true" />Пересчитываем прогноз…</span></div>}
          </div>
          <div className="mt-4" aria-live="polite">
            {recalculating ? null : result ? <>
              <div className="overflow-x-auto border-y border-[color:var(--border)] text-sm"><div className="min-w-[460px]">
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 border-b border-[color:var(--border)] py-2 text-xs font-medium text-[color:var(--text-secondary)]"><span>Показатель</span><span>Без изменений</span><span>С изменениями</span></div>
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 py-2"><span className="text-[color:var(--text-secondary)]">Минимальный остаток</span><span className="tabular-nums">{money(baseMinimum?.p50)}</span><span className="font-medium tabular-nums">{money(scenarioMinimum?.p50)}</span></div>
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 py-2"><span className="text-[color:var(--text-secondary)]">Дата нехватки</span><span>{baseGap ? displayDate(baseGap.date) : "Нет"}</span><span className="font-medium">{scenarioGap ? displayDate(scenarioGap.date) : "Нет"}</span></div>
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2 py-2"><span className="text-[color:var(--text-secondary)]">Вероятность{limitedProbability ? "*" : ""}</span><span>{baseGap && baseForecast ? riskProbabilityText(baseGap, baseForecast) : "—"}</span><span className="font-medium">{scenarioGap && result ? riskProbabilityText(scenarioGap, result) : "—"}</span></div>
                <p className="border-t border-[color:var(--border)] py-2 text-xs font-medium text-[color:var(--text-secondary)]">Изменение минимального остатка: <span className={`tabular-nums ${minimumChange != null && minimumChange < 0 ? "text-[color:var(--danger)]" : minimumChange != null && minimumChange > 0 ? "text-[color:var(--success)]" : "text-[color:var(--text-primary)]"}`}>{minimumChange == null ? "—" : `${minimumChange > 0 ? "+" : ""}${money(minimumChange)}`}</span></p>
              </div></div>
              <p className="mt-3 text-sm text-[color:var(--text-secondary)]"><span className="font-medium text-[color:var(--text-primary)]">Итог: </span>{gapChange}{scenarioGap ? ` По сценарию ${gapAmount(scenarioGap).label.toLowerCase()}: ${money(gapAmount(scenarioGap).amount)} с ${displayDate(scenarioGap.date)}.` : ""}</p>
              {(baseGap || scenarioGap) && <p className="mt-1 text-xs text-[color:var(--text-secondary)]">Неснижаемый резерв: {money(reserve)}. Нехватка — разница между резервом и минимальным прогнозным остатком начиная с первой даты риска; поэтому она не равна модулю отрицательного остатка.</p>}
              {limitedProbability && <p className="mt-1 text-xs text-[color:var(--text-secondary)]">Точная вероятность недоступна: прогноз упрощён, данные устарели или их недостаточно.</p>}
            </> : <div className="border-t border-[color:var(--border)] py-3 text-sm"><p className="font-medium text-[color:var(--text-primary)]">Базовый прогноз</p><p className="mt-1 text-[color:var(--text-secondary)]">Минимальный остаток: {money(baseMinimum?.p50)}{baseGap ? ` · нехватка с ${displayDate(baseGap.date)}` : " · нехватки не прогнозируется"}</p>{baseGap && <p className="mt-1 text-xs text-[color:var(--text-secondary)]">Нехватка считается относительно неснижаемого резерва {money(reserve)}, а не нулевого остатка.</p>}{limitedProbability && <p className="mt-1 text-xs text-[color:var(--text-secondary)]">Точная вероятность недоступна при ограниченной надёжности прогноза.</p>}<p className="mt-2 text-xs text-[color:var(--text-secondary)]">Выберите условие и настройте его, чтобы увидеть сравнение.</p></div>}
          </div>
        </section>
      </div>
      <Dialog open={saveOpen} title={selectedId ? "Сохранить изменения" : "Сохранить сценарий"} className="max-w-sm" onClose={() => setSaveOpen(false)} dismissDisabled={saving}>
        <form className="space-y-4" onSubmit={event => { event.preventDefault(); void saveScenario(); }}>
          <Input label="Название сценария" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required />
          {error && <p role="alert" className="text-sm text-[color:var(--danger)]">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={saving} onClick={() => setSaveOpen(false)}>Отмена</Button>
            <Button type="submit" loading={saving} disabled={!title.trim() || !steps.length || missingClient || !comparison.data || comparison.loading}>Сохранить</Button>
          </div>
        </form>
      </Dialog>
      <ConfirmDialog open={deleting} title="Удалить сценарий?" description={title} loading={saving} onCancel={() => { if (!saving) setDeleting(false); }} onConfirm={async () => { setSaving(true); setError(null); try { await api.request(`/v1/scenarios/${selectedId}`, { method: "DELETE" }); setDeleting(false); resetScenario(); scenarios.refresh(); } catch (cause) { setError(message(cause)); } finally { setSaving(false); } }}>{error && <p role="alert">{error}</p>}</ConfirmDialog>
    </>
  );
}

function StepEditor({ step, clients, events, onChange, onRemove }: { step: Schemas["ScenarioStep"]; clients: Array<{ value: string; label: string }>; events: PlannedEvent[]; onChange: (step: Schemas["ScenarioStep"]) => void; onRemove: () => void }) {
  const titles = { delay_counterparty: "Клиент заплатит позже", scale_revenue: "Изменение выручки", add_expense: "Новый расход", scale_fixed_costs: "Постоянные расходы", move_event: "Перенос события" };
  return <div className="space-y-3 border-b border-[color:var(--border)] pb-4"><div className="flex items-center justify-between gap-2"><ContentHeading level={3}>{titles[step.kind]}</ContentHeading><Button size="sm" variant="ghost" onClick={onRemove}>Убрать</Button></div>
    {(step.kind === "scale_revenue" || step.kind === "scale_fixed_costs") && <Input label={step.kind === "scale_revenue" ? "Изменение поступлений, %" : "Изменение фикс. расходов, %"} type="number" min="-100" max="900" step="1" value={Math.round(((step.factor ?? 1) - 1) * 100)} onChange={e => onChange({ ...step, factor: 1 + Number(e.target.value) / 100 })} />}
    {step.kind === "delay_counterparty" && <><Select density="form" label="Клиент" value={step.counterparty_id ?? ""} options={[{ value: "", label: "Выберите клиента" }, ...clients]} onChange={e => onChange({ ...step, counterparty_id: e.target.value })} /><Input label="Задержка, дней" type="number" min="0" max="365" value={step.delay_days ?? 0} onChange={e => onChange({ ...step, delay_days: Number(e.target.value) })} /></>}
    {step.kind === "add_expense" && <Input label="Сумма, ₽" type="number" min="0" max="10000000000000" step="0.01" value={step.amount ?? 0} onChange={e => onChange({ ...step, amount: Number(e.target.value) })} />}
    {step.kind === "move_event" && <Select density="form" label="Событие" value={step.event_id ?? ""} options={[{ value: "", label: "Выберите событие" }, ...events.filter(e => e.editable).map(e => ({ value: e.id, label: `${displayDate(e.date)} · ${e.title}` }))]} onChange={e => onChange({ ...step, event_id: e.target.value })} />}
    {(step.kind === "add_expense" || step.kind === "move_event") && <Input label="Дата" type="date" value={step.date ?? ""} onChange={e => onChange({ ...step, date: e.target.value })} />}
  </div>;
}
