import * as React from "react";
import { cn } from "@/src/lib/cn";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "brand";
type BadgeTone = "subtle" | "solid" | "outline" | "soft";
type BadgeSize = "sm" | "md" | "lg";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  tone?: BadgeTone;
  size?: BadgeSize;
  dot?: boolean;
  icon?: React.ReactNode;
  clickable?: boolean;
}

const sizeClasses: Record<BadgeSize, string> = {
  sm: "gap-2 text-[16px]",
  md: "gap-2 text-[16px]",
  lg: "gap-2 text-[16px]",
};

const dotSizeClasses: Record<BadgeSize, string> = {
  sm: "h-[9px] w-[9px]",
  md: "h-[9px] w-[9px]",
  lg: "h-[9px] w-[9px]",
};

const toneClasses: Record<BadgeVariant, Record<BadgeTone, string>> = {
  default: {
    subtle: "text-[color:var(--text-primary)]",
    soft: "text-[color:var(--text-primary)]",
    outline: "text-[color:var(--text-primary)]",
    solid: "text-[color:var(--text-primary)]",
  },
  success: {
    subtle: "text-[color:var(--text-primary)]",
    soft: "text-[color:var(--text-primary)]",
    outline: "text-[color:var(--text-primary)]",
    solid: "text-[color:var(--text-primary)]",
  },
  warning: {
    subtle: "text-[color:var(--text-primary)]",
    soft: "text-[color:var(--text-primary)]",
    outline: "text-[color:var(--text-primary)]",
    solid: "text-[color:var(--text-primary)]",
  },
  danger: {
    subtle: "text-[color:var(--text-primary)]",
    soft: "text-[color:var(--text-primary)]",
    outline: "text-[color:var(--text-primary)]",
    solid: "text-[color:var(--text-primary)]",
  },
  brand: {
    subtle: "text-[color:var(--text-primary)]",
    soft: "text-[color:var(--text-primary)]",
    outline: "text-[color:var(--text-primary)]",
    solid: "text-[color:var(--text-primary)]",
  },
};

const dotColorClasses: Record<BadgeVariant, Record<BadgeTone, string>> = {
  default: {
    subtle: "bg-[color:var(--text-muted)]",
    soft: "bg-[color:var(--text-muted)]",
    outline: "bg-[color:var(--text-secondary)]",
    solid: "bg-[color:var(--text-primary)]",
  },
  success: {
    subtle: "bg-[color:var(--success)]",
    soft: "bg-[color:var(--success)]",
    outline: "bg-[color:var(--success)]",
    solid: "bg-[color:var(--success)]",
  },
  warning: {
    subtle: "bg-[color:var(--warning)]",
    soft: "bg-[color:var(--warning)]",
    outline: "bg-[color:var(--warning)]",
    solid: "bg-[color:var(--warning)]",
  },
  danger: {
    subtle: "bg-[color:var(--danger)]",
    soft: "bg-[color:var(--danger)]",
    outline: "bg-[color:var(--danger)]",
    solid: "bg-[color:var(--danger)]",
  },
  brand: {
    subtle: "bg-[color:var(--brand)]",
    soft: "bg-[color:var(--brand)]",
    outline: "bg-[color:var(--brand)]",
    solid: "bg-[color:var(--brand)]",
  },
};

/**
 * Назначение функции: Отображает компонент `Badge` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Badge({
  className,
  variant = "default",
  tone = "subtle",
  size = "md",
  dot: _dot = false,
  icon: _icon,
  clickable = false,
  children,
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center whitespace-nowrap !border-0 !bg-transparent !p-0 !text-[16px] !font-normal !text-[color:var(--text-primary)] !shadow-none",
        "select-none",
        sizeClasses[size],
        toneClasses[variant][tone],
        clickable && "cursor-pointer transition-opacity hover:opacity-80",
        className
      )}
      {...props}
    >
      <span
        className={cn(
          "shrink-0 rounded-full",
          dotSizeClasses[size],
          dotColorClasses[variant][tone]
        )}
        aria-hidden="true"
      />

      {children != null ? <span className="truncate">{children}</span> : null}
    </span>
  );
}
