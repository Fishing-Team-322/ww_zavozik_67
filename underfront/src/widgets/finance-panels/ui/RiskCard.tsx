"use client";

import { AlertTriangle, ArrowUpRight, CheckCircle2 } from "lucide-react";
import { Button } from "@/src/shared/ui/button";

export type CashflowRisk = {
  id: string;
  date: string;
  deficit: number;
  probability?: number | null; // 0..1, calculated by a real model, not UI
  reasons: string[];
  recommendation?: string;
};

export function RiskCard({risk, status = "unknown", onOpenScenario}: {risk: CashflowRisk | null; status?: "unknown" | "clear"; onOpenScenario?: () => void}) {
  return (
    <section className="rounded-[18px] border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
      {risk ? <>
        <div className="flex items-center gap-2 text-sm font-semibold text-[color:var(--danger)]"><AlertTriangle size={18}/> Возможен кассовый разрыв</div>
        <div className="mt-4 flex flex-wrap items-end justify-between gap-2">
          <div><p className="text-xs text-[color:var(--text-secondary)]">Дата риска</p><p className="mt-1 text-xl font-semibold text-[color:var(--text-primary)]">{risk.date}</p></div>
          <div className="text-right"><p className="text-xs text-[color:var(--text-secondary)]">Не хватает</p><p className="mt-1 text-xl font-semibold tabular-nums text-[color:var(--danger)]">{Math.abs(risk.deficit).toLocaleString("ru-RU")} ₽</p></div>
        </div>
        {risk.probability != null && <p className="mt-3 text-sm text-[color:var(--text-secondary)]">Оценка вероятности: <strong className="text-[color:var(--text-primary)]">{Math.round(risk.probability*100)}%</strong></p>}
        {risk.reasons.length > 0 && <div className="mt-4 space-y-1.5 border-t border-[color:var(--divider)] pt-3"><p className="text-xs font-semibold text-[color:var(--text-primary)]">Что влияет на риск</p><ul className="list-inside list-disc space-y-1 text-xs leading-5 text-[color:var(--text-secondary)]">{risk.reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul></div>}
        {risk.recommendation && <p className="mt-3 rounded-lg bg-[color:var(--surface-subtle)] p-3 text-xs leading-5 text-[color:var(--text-primary)]">{risk.recommendation}</p>}
        {onOpenScenario && <Button variant="secondary" className="mt-4 w-full" onClick={onOpenScenario}>Проверить сценарий <ArrowUpRight size={16}/></Button>}
      </> : <div className="flex items-start gap-3"><CheckCircle2 className={status === "clear" ? "text-[color:var(--success)]" : "text-[color:var(--text-muted)]"} size={21}/><div><h3 className="text-sm font-semibold">{status === "clear" ? "Критических рисков не обнаружено" : "Данных о рисках пока нет"}</h3><p className="mt-1 text-xs text-[color:var(--text-secondary)]">{status === "clear" ? "Оценка зависит от полноты входных данных." : "Оценка появится после загрузки данных и расчёта прогноза."}</p></div></div>}
    </section>
  );
}
