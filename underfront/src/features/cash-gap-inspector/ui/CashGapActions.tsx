"use client";

import type { GapAction, GapActionPreview } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { Checkbox } from "@/src/shared/ui/checkbox";
import { gapMuted } from "./styles";

export interface CashGapActionsProps {
  actions: readonly GapAction[];
  previews: readonly GapActionPreview[];
  selectedActionIds: readonly string[];
  disabled?: boolean;
  onToggle: (id: string) => void;
}

export function CashGapActions({ actions, previews, selectedActionIds, disabled, onToggle }: CashGapActionsProps) {
  return <div className="divide-y divide-[color:var(--border-muted)]">
    {actions.map((action) => {
      const checked = selectedActionIds.includes(action.id);
      const conflict = actions.find((candidate) => action.conflictsWith.includes(candidate.id) && selectedActionIds.includes(candidate.id));
      const preview = previews.find((item) => item.actionId === action.id);
      const eliminated = preview?.maximumShortfall === 0;
      const improved = (preview?.improvement ?? 0) > 0;
      return <div key={action.id} className={`flex items-start gap-3 px-4 py-3 transition-colors ${checked ? "bg-[color:var(--sidebar-bg)]" : "hover:bg-[color:var(--nav-item-hover-bg)]"}`}>
        <Checkbox size="sm" checked={checked} onChange={() => onToggle(action.id)} disabled={disabled || Boolean(conflict)} aria-label={`${checked ? "Исключить" : "Включить"}: ${action.title}`} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"><h4 className="text-[13px] font-medium leading-5">{action.title}</h4><span className={`text-[12px] font-medium tabular-nums ${improved ? "text-[color:var(--accent)]" : "text-[color:var(--nav-item-text)]"}`}>{preview ? `${improved ? "−" : ""}${formatRub(Math.abs(preview.improvement))} нехватки` : "Нет оценки"}</span></div>
          <p className={`mt-1 ${gapMuted}`}>{action.description}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] leading-4"><span className={eliminated ? "text-[color:var(--accent)]" : "text-[color:var(--nav-item-text)]"}>{eliminated ? "Разрыв устранён" : improved ? "Нехватка уменьшится" : "Недостаточно для устранения"}</span><span className="tabular-nums text-[color:var(--nav-item-text)]">Стоимость: {action.cost ? formatRub(action.cost.amount) : "не оценена"}</span></div>
          {conflict ? <p className="mt-1 text-[12px] leading-4 text-[color:var(--warning)]">Для выбора выключите «{conflict.title}».</p> : null}
          <details className={`mt-1 ${gapMuted}`}><summary className="w-fit cursor-pointer rounded-[4px] hover:text-[color:var(--nav-item-active-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)]">Условия</summary><p className="pt-1">{action.conditions}</p></details>
        </div>
      </div>;
    })}
  </div>;
}
