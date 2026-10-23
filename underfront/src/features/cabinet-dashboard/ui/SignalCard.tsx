"use client";

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { cn } from "@/src/lib/cn";

export type SignalLevel = "info" | "warning" | "critical";

export type Signal = {
  id: string;
  level: SignalLevel;
  title: string;
  detail: string;
  /** The rule that produced this line, named so the reader can check it. */
  basis: string;
  href?: string;
  action?: string;
};

const LEVEL_STYLE: Record<SignalLevel, { dot: string; border: string }> = {
  info: {
    dot: "bg-[color:var(--accent)]",
    border: "border-[color:var(--border)]",
  },
  warning: {
    dot: "bg-[color:var(--warning)]",
    border: "border-[color:var(--warning)]/40",
  },
  critical: {
    dot: "bg-[color:var(--danger)]",
    border: "border-[color:var(--danger)]/50",
  },
};

/**
 * One observation about the period, with the rule that produced it.
 *
 * There is no model behind these: each is a threshold over a number already on
 * the page, and `basis` says which. Naming the rule is what separates a signal
 * a supervisor can verify from a recommendation they have to trust.
 */
/**
 * Назначение функции: One observation about the period, with the rule that produced it. There is no model behind these: each is a threshold over a number already on the page, and `basis` says which. Naming the rule is what separates a signal a supervisor can verify from a recommendation they have to trust.
 * Зачем используется: Поддерживает отдельное действие или сценарий пользователя.
 */
export function SignalCard({ signal }: { signal: Signal }) {
  const style = LEVEL_STYLE[signal.level];
  const body = (
    <>
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className={cn("mt-1.5 size-2 shrink-0 rounded-full", style.dot)}
        />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-[color:var(--text-primary)]">
            {signal.title}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-[color:var(--text-secondary)]">
            {signal.detail}
          </p>
          <p className="mt-1.5 text-[11px] text-[color:var(--text-secondary)]/75">
            {signal.basis}
          </p>
        </div>
        {signal.href ? (
          <ArrowUpRight
            size={14}
            aria-hidden
            className="mt-0.5 shrink-0 text-[color:var(--text-secondary)]"
          />
        ) : null}
      </div>
    </>
  );

  const shell = cn(
    "block rounded-xl border bg-[color:var(--surface)] p-3.5 text-left transition",
    style.border,
    signal.href && "hover:bg-[color:var(--surface-subtle)]"
  );

  return signal.href ? (
    <Link href={signal.href} className={shell}>
      {body}
    </Link>
  ) : (
    <div className={shell}>{body}</div>
  );
}
