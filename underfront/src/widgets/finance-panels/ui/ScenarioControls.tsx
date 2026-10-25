"use client";
import { ContentHeading } from "@/src/shared/ui/content";

import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button } from "@/src/shared/ui/button";

export type ScenarioParams = { paymentDelayDays: number; revenueDropPercent: number; unexpectedExpense: number };
export const DEFAULT_SCENARIO: ScenarioParams = { paymentDelayDays: 0, revenueDropPercent: 0, unexpectedExpense: 0 };

/** Inputs only. Pass params to your API to compute the scenario; don't forecast in this component. */
export function ScenarioControls({value, onChange, onReset, visibleKeys, bare = false, loading = false}: {value: ScenarioParams; onChange: (next:ScenarioParams)=>void; onReset?:()=>void; visibleKeys?: Array<keyof ScenarioParams>; bare?:boolean; loading?:boolean}) {
  const fields: Array<{key:keyof ScenarioParams; label:string; min:number; max:number; step:number; suffix:string}> = [
    {key:"paymentDelayDays", label:"Задержка крупного платежа", min:0,max:28,step:7,suffix:"дн."},
    {key:"revenueDropPercent",label:"Снижение поступлений",min:0,max:30,step:5,suffix:"%"},
    {key:"unexpectedExpense",label:"Внеплановый расход",min:0,max:500000,step:25000,suffix:"₽"},
  ];
  return <div className={bare ? "" : "border border-[color:var(--border)] bg-[color:var(--surface)] p-4"}>
    {!bare && <div className="mb-5 flex items-center justify-between gap-2"><ContentHeading level={3} className="flex items-center gap-2"><SlidersHorizontal size={17}/> Свои изменения</ContentHeading><Button variant="outline" size="md" onClick={onReset ?? (()=>onChange(DEFAULT_SCENARIO))} disabled={loading}><RotateCcw size={14}/> Сбросить</Button></div>}
    <div className="space-y-5">{fields.filter(field => !visibleKeys || visibleKeys.includes(field.key)).map(f=><label key={f.key} className="block space-y-2">
      <div className="flex items-baseline justify-between gap-3 text-sm"><span className="font-medium text-[color:var(--text-primary)]">{f.label}</span><strong className="shrink-0 tabular-nums text-[color:var(--text-primary)]">{value[f.key].toLocaleString("ru-RU")} {f.suffix}</strong></div>
      <input className="block h-5 w-full cursor-pointer accent-[var(--accent)]" type="range" disabled={loading} min={f.min} max={f.max} step={f.step} value={value[f.key]} onChange={e=>onChange({...value,[f.key]:Number(e.target.value)})}/>
    </label>)}</div>
    {!bare && <p className="mt-5 border-t border-[color:var(--border)] pt-3 text-xs text-[color:var(--text-secondary)]">Меняются только условия прогноза. Базовый план остаётся прежним.</p>}
  </div>;
}
