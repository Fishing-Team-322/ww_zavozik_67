"use client";

import { TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/src/shared/lib/cn";

/**
 * Change against the previous period, with a direction the reader can act on.
 *
 * Up is not automatically good: fewer failed payments is an improvement, more
 * disputes is not. `goodWhen` says which way this particular number should
 * move, so the colour means "as intended" rather than "larger".
 */
/**
 * Назначение функции: Change against the previous period, with a direction the reader can act on. Up is not automatically good: fewer failed payments is an improvement, more disputes is not. `goodWhen` says which way this particular number should move, so the colour means "as intended" rather than "larger".
 * Зачем используется: Поддерживает отдельное действие или сценарий пользователя.
 */
export function TrendChip({
  change,
  goodWhen = "up",
  className,
}: {
  change: number | null;
  goodWhen?: "up" | "down" | "neutral";
  className?: string;
}) {
  if (change === null || !Number.isFinite(change)) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full border border-[color:var(--border)] px-2 py-0.5 text-[11px] font-medium text-[color:var(--text-secondary)]",
          className
        )}
        title="Не с чем сравнивать: за прошлый период данных нет"
      >
        нет базы
      </span>
    );
  }

  const up = change >= 0;
  const good =
    goodWhen === "neutral" ? null : goodWhen === "up" ? up : !up;
  const tone =
    good === null
      ? "border-[color:var(--border)] text-[color:var(--text-secondary)]"
      : good
        ? "border-[color:var(--success)]/40 bg-[color:var(--success)]/10 text-[color:var(--success)]"
        : "border-[color:var(--danger)]/40 bg-[color:var(--danger)]/10 text-[color:var(--danger)]";

  const Icon = up ? TrendingUp : TrendingDown;
  const rounded = Math.abs(change) >= 10 ? Math.round(change) : Math.round(change * 10) / 10;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold tabular-nums",
        tone,
        className
      )}
    >
      <Icon size={12} aria-hidden />
      {up ? "+" : "−"}
      {Math.abs(rounded).toLocaleString("ru-RU")}%
    </span>
  );
}
