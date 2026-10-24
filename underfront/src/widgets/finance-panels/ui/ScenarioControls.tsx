"use client";

import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { Button } from "@/src/shared/ui/button";

export type ScenarioParams = { paymentDelayDays: number; revenueDropPercent: number; unexpectedExpense: number };
export const DEFAULT_SCENARIO: ScenarioParams = { paymentDelayDays: 0, revenueDropPercent: 0, unexpectedExpense: 0 };

/** Inputs only. Pass params to your API to compute the scenario; don't forecast in this component. */
export function ScenarioControls({value, onChange, loading = false}: {value: ScenarioParams; onChange: (next:ScenarioParams)=>void; loading?:boolean}) {
  const fields: Array<{key:keyof ScenarioParams; label:string; min:number; max:number; step:number; suffix:string}> = [
    {key:"paymentDelayDays", label:"Задержка крупного платежа", min:0,max:28,step:7,suffix:"дн."},
    {key:"revenueDropPercent",label:"Снижение поступлений",min:0,max:30,step:5,suffix:"%"},
    {key:"unexpectedExpense",label:"Внеплановый расход",min:0,max:500000,step:25000,suffix:"₽"},
  ];
  return <div className="rounded-[18px] border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
    <div className="mb-5 flex items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-base font-semibold"><SlidersHorizontal size={18}/> Что если?</h3><Button variant="ghost" size="sm" onClick={()=>onChange(DEFAULT_SCENARIO)} disabled={loading}><RotateCcw size={14}/> Сброс</Button></div>
    <div className="space-y-5">{fields.map(f=><label key={f.key} className="block space-y-2">
      <div className="flex justify-between gap-2 text-xs"><span className="text-[color:var(--text-secondary)]">{f.label}</span><strong className="tabular-nums">{value[f.key].toLocaleString("ru-RU")} {f.suffix}</strong></div>
      <input className="block w-full accent-[var(--accent)]" type="range" disabled={loading} min={f.min} max={f.max} step={f.step} value={value[f.key]} onChange={e=>onChange({...value,[f.key]:Number(e.target.value)})}/>
    </label>)}</div>
    <p className="mt-5 text-xs text-[color:var(--text-secondary)]">Изменение условий показывает возможный результат. Базовый план остаётся прежним.</p>
  </div>;
}
