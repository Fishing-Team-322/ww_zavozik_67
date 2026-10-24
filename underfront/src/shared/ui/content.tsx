import type { HTMLAttributes } from "react";
import { cn } from "@/src/shared/lib/cn";

/** Semantic roles for page content; never applied to the application shell. */
export const contentTypography = {
  page: "text-xl font-semibold leading-7",
  section: "text-base font-semibold leading-6",
  group: "text-sm font-medium leading-5",
  body: "text-[13px] font-normal leading-5",
  description: "text-xs font-normal leading-[18px]",
  meta: "text-xs font-normal leading-4",
  label: "text-xs font-medium leading-4",
  financial: "text-[13px] font-medium leading-5 tabular-nums",
  kpi: "text-2xl font-semibold leading-8 tabular-nums",
} as const;

export function ContentHeading({
  level = 2, className, ...props
}: HTMLAttributes<HTMLHeadingElement> & { level?: 1 | 2 | 3 | 4 }) {
  const Tag = level === 1 ? "h1" : level === 2 ? "h2" : level === 3 ? "h3" : "h4";
  return <Tag className={cn("text-[color:var(--text-primary)]", contentTypography[level === 1 ? "page" : level === 2 ? "section" : "group"], className)} {...props} />;
}

export function ContentText({
  as: Tag = "p", variant = "body", tone, className, ...props
}: HTMLAttributes<HTMLElement> & {
  as?: "p" | "span" | "div";
  variant?: "body" | "description" | "meta" | "label" | "financial" | "kpi";
  tone?: "default" | "muted" | "danger" | "warning" | "success" | "accent";
}) {
  const colors = {
    default: "text-[color:var(--text-primary)]",
    muted: "text-[color:var(--text-secondary)]",
    danger: "text-[color:var(--danger)]",
    warning: "text-[color:var(--warning)]",
    success: "text-[color:var(--success)]",
    accent: "text-[color:var(--accent)]",
  };
  const resolvedTone = tone ?? (variant === "description" || variant === "meta" ? "muted" : "default");
  return <Tag className={cn(contentTypography[variant], colors[resolvedTone], className)} {...props} />;
}

/** A compact feed entry, with the same divider and text rhythm as analytical rows. */
export function ContentListItem({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <article className={cn("space-y-2 border-b border-[color:var(--divider)] py-3", contentTypography.body, className)} {...props} />;
}
