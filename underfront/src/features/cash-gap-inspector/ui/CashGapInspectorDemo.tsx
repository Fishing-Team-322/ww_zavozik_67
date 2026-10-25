"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Trash2, X } from "lucide-react";
import { formatGapDate, type CashGapDetails, type CashGapInspectorStatus, type GapSimulation, type SavedGapScenario } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { Button } from "@/src/shared/ui/button";
import { Dialog } from "@/src/shared/ui/dialog";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";
import { createMockCashGapService } from "../api/mock-service";
import { CashGapInspector } from "./CashGapInspector";
import { gapMuted, gapPanel } from "./styles";

type DemoMode = "ready" | "loading" | "empty" | "error";
const COMPANY = "puls-demo";
const GAP = "gap-november-2026";

export function CashGapInspectorDemo() {
  const [data, setData] = useState<CashGapDetails | null>(null);
  const [simulation, setSimulation] = useState<GapSimulation | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [status, setStatus] = useState<CashGapInspectorStatus>("loading");
  const [mode, setMode] = useState<DemoMode>("ready");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedGapScenario[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const saveCounter = useRef(0);

  const load = useCallback(async (nextMode: DemoMode) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setMode(nextMode);
    setStatus("loading");
    setError(null);
    setData(null);
    setSimulation(null);
    setSelected([]);
    setNotice("");
    if (nextMode === "loading") return;
    try {
      const service = createMockCashGapService({ empty: nextMode === "empty" });
      const details = await service.getGap(COMPANY, GAP, controller.signal);
      if (controller.signal.aborted) return;
      if (!details) { setStatus("empty"); return; }
      setData(details);
      const initial = await service.simulate(COMPANY, GAP, { actionIds: [] }, controller.signal);
      if (controller.signal.aborted) return;
      setSimulation(initial);
      if (nextMode === "error") await createMockCashGapService({ failSimulation: true }).simulate(COMPANY, GAP, { actionIds: [] }, controller.signal);
      if (!controller.signal.aborted) setStatus("ready");
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : "Не удалось загрузить расчёт.");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load("ready"); }, 0);
    return () => { window.clearTimeout(timer); request.current?.abort(); };
  }, [load]);

  async function recalculate(actionIds: string[]) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setSelected(actionIds);
    setStatus("simulating");
    setMode("ready");
    setError(null);
    setNotice("");
    try {
      const next = await createMockCashGapService().simulate(COMPANY, GAP, { actionIds }, controller.signal);
      if (controller.signal.aborted) return;
      // Один снимок результата одновременно обновляет график, сводку и таблицу.
      setSimulation(next);
      setStatus("ready");
    } catch (failure) {
      if (controller.signal.aborted) return;
      setError(failure instanceof Error ? failure.message : "Не удалось пересчитать сценарий.");
      setStatus("error");
    }
  }

  function saveScenario() {
    if (!simulation || status !== "ready" || !name.trim()) return;
    saveCounter.current += 1;
    setSaved((current) => [...current, { id: `local-${saveCounter.current}`, name: name.trim(), actionIds: [...simulation.actionIds], result: structuredClone(simulation) }]);
    setSaveOpen(false);
    setNotice(`«${name.trim()}» сохранён в этой сессии. Финансовые данные не изменены.`);
  }

  return <section aria-labelledby="cash-gap-demo-heading" className="min-w-0 space-y-4 border-t border-[color:var(--border)] pt-6 text-[13px] leading-5 text-[color:var(--nav-item-active-text)]">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h2 id="cash-gap-demo-heading" className="text-[20px] font-semibold leading-6 tracking-tight">Анализ кассового разрыва</h2><p className={`mt-1 ${gapMuted}`}>Демонстрационная симуляция · {data ? `срез на ${formatGapDate(data.scenario.asOf, true)}` : "ноябрь 2026"}. Вероятность — mock-значение, без ML-прогноза.</p></div>
      <Select density="form" size="lg" label="Демо-состояние" value={mode} onChange={(event) => { void load(event.target.value as DemoMode); }} options={[{ value: "ready", label: "Данные загружены" }, { value: "loading", label: "Загрузка" }, { value: "empty", label: "Нет данных" }, { value: "error", label: "Ошибка расчёта" }]} />
    </header>

    <CashGapInspector data={data} simulation={simulation} selectedActionIds={selected} status={status} error={error}
      onToggleAction={(id) => { if (status !== "simulating") void recalculate(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id]); }}
      onReset={() => { void recalculate([]); }}
      onRetry={() => { if (data && simulation) void recalculate(selected); else void load("ready"); }}
      onSaveScenario={() => { setName(`Сценарий ${saved.length + 1}`); setSaveOpen(true); }} />

    {notice ? <div role="status" aria-live="polite" className="flex items-start justify-between gap-3 text-[12px]"><p>{notice}</p><Button variant="ghost" size="icon" aria-label="Закрыть уведомление" onClick={() => setNotice("")}><X /></Button></div> : null}
    {saved.length ? <section className={gapPanel} aria-label="Локальные сценарии"><div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--border)] px-4 py-3"><h3 className="text-[15px] font-semibold">Сохранённые сценарии</h3><span className={gapMuted}>Только в текущей сессии</span></div><ul className="divide-y divide-[color:var(--border-muted)]">{saved.map((item) => <li key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-2"><div className="min-w-0 flex-1"><p className="break-words font-medium">{item.name}</p><p className={`${gapMuted} tabular-nums`}>{item.actionIds.length} действий · нехватка {formatRub(item.result.alternative.maximumShortfall)} · стоимость {formatRub(item.result.totalCost)}</p></div><Button size="lg" variant="outline" disabled={!data || status === "loading" || status === "simulating"} onClick={() => { void recalculate([...item.actionIds]); }}>Загрузить</Button><Button size="icon" variant="ghost" aria-label={`Удалить сценарий ${item.name}`} onClick={() => { setSaved((current) => current.filter((candidate) => candidate.id !== item.id)); setNotice(`Сценарий «${item.name}» удалён.`); }}><Trash2 /></Button></li>)}</ul></section> : null}

    <Dialog open={saveOpen} onClose={() => setSaveOpen(false)} title="Сохранить локальный сценарий" description="Сохраняются выбранные действия и результат симуляции. После перезагрузки страницы они будут удалены." className="max-w-[420px]">
      <form onSubmit={(event) => { event.preventDefault(); saveScenario(); }} className="space-y-4">
        <Input inputSize="lg" label="Название сценария" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} required />
        <div className="flex justify-end gap-2"><Button type="button" size="lg" variant="outline" onClick={() => setSaveOpen(false)}>Отмена</Button><Button type="submit" size="lg" disabled={!name.trim() || status !== "ready"}>Сохранить</Button></div>
      </form>
    </Dialog>
  </section>;
}
