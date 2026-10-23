"use client";

import type { ReactNode } from "react";

import { cn } from "@/src/lib/cn";

import { Sparkline } from "./Sparkline";
import { TrendChip } from "./TrendChip";

/**
 * One headline number: what it is, what it now reads, which way it moved, and
 * the shape it took getting there.
 *
 * The sparkline sits under the number rather than behind it. A series drawn
 * through the digits looks richer and costs the reader the one thing the tile
 * exists for, which is reading the number.
 */
/**
 * Назначение функции: One headline number: what it is, what it now reads, which way it moved, and the shape it took getting there. The sparkline sits under the number rather than behind it. A series drawn through the digits looks richer and costs the reader the one thing the tile exists for, which is reading the number.
 * Зачем используется: Поддерживает отдельное действие или сценарий пользователя.
 */
export function MetricTile({
  label,
  value,
  hint,
  change,
  goodWhen = "up",
  series,
  color,
  loading = false,
  footer,
  className,
}: {
  label: string;
  value: string;
  hint?: string;
  change?: number | null;
  goodWhen?: "up" | "down" | "neutral";
  series?: number[];
  color: string;
  loading?: boolean;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-[var(--radius-lg)] border border-[color:var(--border)] bg-[color:var(--surface)] p-5",
        className
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span className="text-[13px] font-medium text-[color:var(--text-secondary)]">
          {label}
        </span>
        {change !== undefined ? (
          <TrendChip change={change} goodWhen={goodWhen} />
        ) : null}
      </div>

      <div>
        <div
          className={cn(
            "text-[30px] font-semibold leading-none tracking-tight tabular-nums text-[color:var(--text-primary)]",
            loading && "animate-pulse text-[color:var(--text-secondary)]/40"
          )}
        >
          {loading ? "———" : value}
        </div>
        {hint ? (
          <div className="mt-1.5 text-xs text-[color:var(--text-secondary)]">
            {hint}
          </div>
        ) : null}
      </div>

      {series && series.length > 1 ? (
        <Sparkline values={series} color={color} height={38} />
      ) : null}

      {footer}
    </div>
  );
}
