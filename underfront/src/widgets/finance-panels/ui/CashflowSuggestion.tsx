"use client";

import type { Schemas } from "@/src/shared/api";
import { displayDate, rubles } from "@/src/entities/forecast";

export function CashflowSuggestion({ action, compact = false }: { action: Schemas["Action"]; compact?: boolean }) {
  const effect = action.effect;
  const pessimistic = (effect.baseline_shortfall ?? 0) <= 0;
  const before = pessimistic ? effect.baseline_shortfall_p90 : effect.baseline_shortfall;
  const after = pessimistic ? effect.new_shortfall_p90 : effect.new_shortfall;
  const reduction = pessimistic ? effect.shortfall_p90_reduction : effect.shortfall_reduction;
  return <div className="space-y-2 text-xs text-[color:var(--text-secondary)]">
    <p>{action.explanation ?? action.description}</p>
    <div className="rounded-md bg-[color:var(--sidebar-bg)] p-3" aria-label="Расчёт эффекта">
      <p>{pessimistic ? "Нехватка в неблагоприятном варианте" : "Нехватка по базовому прогнозу"}</p>
      <p className="mt-1 text-sm font-semibold tabular-nums text-[color:var(--text-primary)]">
        {before == null ? "Нет оценки" : rubles(before)} → {after == null ? "Нет оценки" : rubles(after)}
      </p>
      {reduction != null && <p className="mt-1">{reduction > 0 ? `Уменьшение нехватки: ${rubles(reduction)}` : reduction < 0 ? `Нехватка увеличится на ${rubles(-reduction)}` : "Максимальная нехватка не изменится"}</p>}
      <p className="mt-1">{effect.closes_gap ? "По расчёту разрыв не ожидается на выбранном горизонте" : effect.new_gap_date ? `Нехватка сохраняется с ${displayDate(effect.new_gap_date)}` : "Риск нехватки сохраняется"}</p>
      {!compact && effect.new_min_balance != null && <p className="mt-1 tabular-nums">Минимальный базовый остаток: {rubles(effect.new_min_balance)}</p>}
      {!compact && effect.probability_reliable && effect.baseline_probability != null && <p className="mt-1 tabular-nums">Вероятность нехватки: {Math.round(effect.baseline_probability * 100)}% → {Math.round(effect.new_probability * 100)}%</p>}
    </div>
    {action.conditions && <p>{action.conditions}</p>}
    {action.date && <p className="tabular-nums">{action.original_date ? `${displayDate(action.original_date)} → ` : "Плановая дата: "}{displayDate(action.date)}{action.amount != null ? ` · ${rubles(action.amount)}` : ""}</p>}
    <p>{action.cost_known === false ? "Стоимость не оценена" : `Стоимость: ${rubles(action.cost)}`} · {action.explanation_source === "llm" ? "Пояснение модели, эффект рассчитан сервисом" : "Расчёт по данным компании"}</p>
  </div>;
}
