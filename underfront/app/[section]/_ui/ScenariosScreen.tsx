"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import Link from "next/link";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import {
  api,
  message,
  type Forecast,
  type Schemas,
  type PlannedEvent,
} from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select, ConfirmDialog } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import {
  CashflowForecastChart,
  DEFAULT_SCENARIO,
  ScenarioControls,
  type ScenarioParams,
  RiskCard,
} from "@/src/widgets/finance-panels";
import { chartDays, riskView } from "@/src/entities/forecast";
import { money, percent } from "./finance-utils";
import { FinanceState, ForecastNotice } from "./FinanceState";

export function ScenariosScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const forecast = useApiResource<Forecast>(`${base}/forecast`);
  const events = useApiResource<PlannedEvent[]>(`${base}/events`);
  const [params, setParams] = useState<ScenarioParams>(DEFAULT_SCENARIO);
  const [counterparty, setCounterparty] = useState("");
  const [date, setDate] = useState("");
  const [title, setTitle] = useState("Мой сценарий");
  const scenarios = useApiResource<Schemas["Scenario"][]>(`${base}/scenarios`);
  const presets = useApiResource<Array<{ kind: Schemas["ScenarioStep"]["kind"]; title: string }>>("/v1/scenario-presets");
  const [selectedId, setSelectedId] = useState("");
  const [customSteps, setCustomSteps] = useState<Schemas["ScenarioStep"][] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [fixedIncrease, setFixedIncrease] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sliderSteps: Schemas["ScenarioStep"][] = [];
  if (params.revenueDropPercent)
    sliderSteps.push({
      kind: "scale_revenue",
      factor: 1 - params.revenueDropPercent / 100,
    });
  if (params.unexpectedExpense && forecast.data)
    sliderSteps.push({
      kind: "add_expense",
      amount: params.unexpectedExpense,
      date: date || forecast.data.points[0]?.date || "",
    });
  if (params.paymentDelayDays && counterparty)
    sliderSteps.push({
      kind: "delay_counterparty",
      counterparty_id: counterparty,
      delay_days: params.paymentDelayDays,
    });
  if (fixedIncrease) sliderSteps.push({ kind: "scale_fixed_costs", factor: 1 + fixedIncrease / 100 });
  const steps = customSteps ?? sliderSteps;
  const missingClient = customSteps === null && params.paymentDelayDays > 0 && !counterparty;
  const savedCompare = useApiResource<Schemas["ScenarioComparison"]>(selectedId && !dirty ? `/v1/scenarios/${selectedId}/compare` : null);
  const compare = useApiResource<Schemas["ScenarioComparison"]>(
    steps.length && forecast.data && !missingClient && (!selectedId || dirty)
      ? `${base}/scenarios/preview`
      : null,
    { method: "POST", json: { steps } },
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
  const result = comparison.data?.scenario;
  const riskForecast = result || forecast.data;
  return (
    <>
      <ContentHeading level={1} className="mb-6">Сценарии</ContentHeading>
      <FinanceState
        loading={forecast.loading || scenarios.loading || presets.loading}
        error={forecast.error || comparison.error || scenarios.error || presets.error || events.error || error}
        retry={() => {
          forecast.refresh();
          compare.refresh(); savedCompare.refresh(); scenarios.refresh(); presets.refresh(); events.refresh();
        }}
      />
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="grid grid-cols-2 items-end gap-3">
            <Select density="form" size="md" label="Сохранённый сценарий" value={selectedId} options={[{ value: "", label: "Новый сценарий" }, ...(scenarios.data ?? []).map(s => ({ value: s.id, label: s.title }))]} onChange={e => { const scenario = scenarios.data?.find(s => s.id === e.target.value); setSelectedId(scenario?.id ?? ""); setCustomSteps(scenario?.steps ?? null); setTitle(scenario?.title ?? "Мой сценарий"); setDirty(false); setSaved(null); }} />
            <Select density="form" size="md" label="Добавить из пресета" value="" options={[{ value: "", label: "Выберите условие" }, ...(presets.data ?? []).map(p => ({ value: p.kind, label: p.title }))]} onChange={e => { const kind = e.target.value as Schemas["ScenarioStep"]["kind"]; if (!kind) return; setCustomSteps([...steps, kind === "scale_revenue" ? { kind, factor: 0.8 } : kind === "scale_fixed_costs" ? { kind, factor: 1.1 } : kind === "delay_counterparty" ? { kind, delay_days: 7, counterparty_id: clients[0]?.value } : { kind, amount: 0, date: forecast.data?.points[0]?.date ?? "" }]); setDirty(true); }} />
          </div>
          {customSteps ? <div className="space-y-3">{customSteps.map((step, index) => <StepEditor key={index} step={step} clients={clients} events={events.data ?? []} onChange={value => { setCustomSteps(customSteps.map((s, i) => i === index ? value : s)); setDirty(true); setSaved(null); }} onRemove={() => { setCustomSteps(customSteps.filter((_, i) => i !== index)); setDirty(true); }} />)}<Button variant="outline" onClick={() => { setCustomSteps([...customSteps, { kind: "move_event", event_id: events.data?.find(e => e.editable)?.id, date: forecast.data?.points[0]?.date ?? "" }]); setDirty(true); }}>Добавить перенос события</Button><Button variant="ghost" onClick={() => { setSelectedId(""); setCustomSteps(null); setDirty(true); }}>Новый сценарий с ползунками</Button></div> : <><ScenarioControls
            value={params}
            onChange={(value) => {
              setParams(value); setDirty(true);
              setSaved(null);
            }}
          />
          {params.paymentDelayDays > 0 && (
            <Select density="form"
              size="md"
              label="Клиент с плановым поступлением"
              placeholder="Выберите клиента"
              value={counterparty}
              onChange={(event) => setCounterparty(event.target.value)}
              options={clients}
            />
          )}
          {missingClient && (
            <ContentText variant="description" tone="muted" >
              Для переноса выберите клиента с ожидаемым поступлением. Его можно
              добавить в календаре.
            </ContentText>
          )}
          {params.unexpectedExpense > 0 && (
            <Input
              type="date"
              label="Дата внепланового расхода"
              min={forecast.data?.points[0]?.date}
              max={forecast.data?.points.at(-1)?.date}
              value={date || forecast.data?.points[0]?.date || ""}
              onChange={(event) => setDate(event.target.value)}
            />
          )}
          </>}
          <div className={customSteps ? "space-y-3" : "grid grid-cols-2 gap-3"}>
            {!customSteps && <Input label="Фикс. расходы +%" type="number" min="0" max="900" value={fixedIncrease} onChange={e => { setFixedIncrease(Number(e.target.value)); setDirty(true); }} />}
            <Input
              label="Название сценария"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={200}
            />
          </div>
          <Button
            disabled={!title.trim() || !steps.length || missingClient || !comparison.data || comparison.loading}
            loading={saving}
            onClick={async () => {
              setSaving(true);
              setError(null);
              try {
                const stored = await api.request<Schemas["Scenario"]>(selectedId ? `/v1/scenarios/${selectedId}` : `${base}/scenarios`, {
                  method: selectedId ? "PATCH" : "POST",
                  json: { title, steps },
                });
                setSelectedId(stored.id); setCustomSteps(stored.steps); setDirty(false);
                setSaved("Сценарий сохранён.");
              } catch (error) {
                setError(message(error));
              } finally {
                setSaving(false);
              }
            }}
          >
            Сохранить сценарий
          </Button>
          {selectedId && !dirty && <Link className="block text-sm text-[color:var(--accent)] underline" href={`/forecast?scenario=${encodeURIComponent(selectedId)}`}>Открыть прогноз по сценарию</Link>}
          {selectedId && <Button variant="ghost" onClick={() => setDeleting(true)}>Удалить сценарий</Button>}
          {saved && (
            <ContentText variant="body" role="status" >
              {saved}
            </ContentText>
          )}
        </div>
        <SectionCard className="min-w-0">
          <ContentHeading level={2} className="mb-4">
            Базовый и негативный прогноз
          </ContentHeading>
          <ForecastNotice forecast={comparison.data?.base || forecast.data} />
          <CashflowForecastChart
            days={
              forecast.data
                ? chartDays(comparison.data?.base || forecast.data, result)
                : []
            }
            showBounds
          />
          {!steps.length && (
            <ContentText variant="description" tone="muted" className="mt-4">
              Измените параметры, чтобы рассчитать сценарий.
            </ContentText>
          )}
          <div className={`mt-4 grid gap-3 ${comparison.data ? "sm:grid-cols-2 lg:grid-cols-3" : ""}`}>
            {comparison.data && [{ label: "Было", forecast: comparison.data.base }, { label: "Стало", forecast: comparison.data.scenario }].map(({ label, forecast: f }) => { const minimum = f.points.reduce<(typeof f.points)[number] | null>((min, p) => !min || p.p50 < min.p50 ? p : min, null); return <div key={label} className="min-w-0 space-y-1 rounded-md border border-[color:var(--border)] p-3 text-sm leading-5"><ContentHeading level={3} >{label}</ContentHeading><p>Минимум: {money(minimum?.p50)} · {minimum?.date ?? "Нет даты"}</p><p>Разрыв: {f.gaps[0] ? `${f.gaps[0].date} · ${money(f.gaps[0].shortfall)}` : "Не найден"}</p><p>Вероятность: {percent(f.gaps[0]?.probability)}</p></div>; })}
            <div className="min-w-0 [&>section]:h-full">
            <RiskCard
              compact
              risk={
                riskForecast?.gaps[0] ? riskView(riskForecast.gaps[0]) : null
              }
              status={
                riskForecast && !riskForecast.gaps.length ? "clear" : "unknown"
              }
            />
            </div>
          </div>
        </SectionCard>
      </div>
      <ConfirmDialog open={deleting} title="Удалить сценарий?" description={title} loading={saving} onCancel={() => { if (!saving) setDeleting(false); }} onConfirm={async () => { setSaving(true); setError(null); try { await api.request(`/v1/scenarios/${selectedId}`, { method: "DELETE" }); setDeleting(false); setSelectedId(""); setCustomSteps(null); setDirty(false); } catch (cause) { setError(message(cause)); } finally { setSaving(false); } }}>{error && <p role="alert">{error}</p>}</ConfirmDialog>
    </>
  );
}

function StepEditor({ step, clients, events, onChange, onRemove }: { step: Schemas["ScenarioStep"]; clients: Array<{ value: string; label: string }>; events: PlannedEvent[]; onChange: (step: Schemas["ScenarioStep"]) => void; onRemove: () => void }) {
  const titles = { delay_counterparty: "Клиент заплатит позже", scale_revenue: "Изменение выручки", add_expense: "Новый расход", scale_fixed_costs: "Постоянные расходы", move_event: "Перенос события" };
  return <div className="space-y-2 rounded-md border border-[color:var(--border)] p-3"><ContentHeading level={3} >{titles[step.kind]}</ContentHeading>
    {(step.kind === "scale_revenue" || step.kind === "scale_fixed_costs") && <Input label="Множитель (1 = без изменения)" type="number" min="0" max="10" step="0.01" value={step.factor ?? 1} onChange={e => onChange({ ...step, factor: Number(e.target.value) })} />}
    {step.kind === "delay_counterparty" && <><Select density="form" label="Клиент" value={step.counterparty_id ?? ""} options={[{ value: "", label: "Выберите клиента" }, ...clients]} onChange={e => onChange({ ...step, counterparty_id: e.target.value })} /><Input label="Задержка, дней" type="number" min="0" max="365" value={step.delay_days ?? 0} onChange={e => onChange({ ...step, delay_days: Number(e.target.value) })} /></>}
    {step.kind === "add_expense" && <Input label="Сумма, ₽" type="number" min="0" max="10000000000000" step="0.01" value={step.amount ?? 0} onChange={e => onChange({ ...step, amount: Number(e.target.value) })} />}
    {step.kind === "move_event" && <Select density="form" label="Событие" value={step.event_id ?? ""} options={[{ value: "", label: "Выберите событие" }, ...events.filter(e => e.editable).map(e => ({ value: e.id, label: `${e.date} · ${e.title}` }))]} onChange={e => onChange({ ...step, event_id: e.target.value })} />}
    {(step.kind === "add_expense" || step.kind === "move_event") && <Input label="Дата" type="date" value={step.date ?? ""} onChange={e => onChange({ ...step, date: e.target.value })} />}
    <Button size="sm" variant="ghost" onClick={onRemove}>Удалить условие</Button>
  </div>;
}
