"use client";

import * as React from "react";
import { cn } from "@/src/lib/cn";

type Size = "sm" | "md" | "lg";
type IconKind = "check" | "dot" | "minus";

export interface CheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "size" | "onChange"
> {
  checked?: boolean;
  indeterminate?: boolean;
  size?: Size;
  icon?: IconKind;
  label?: React.ReactNode;
  className?: string;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

const SIZE_MAP: Record<Size, { box: string; icon: string; label: string }> = {
  sm: { box: "h-4 w-4", icon: "h-3 w-3", label: "text-sm" },
  md: { box: "h-5 w-5", icon: "h-4 w-4", label: "text-sm" },
  lg: { box: "h-6 w-6", icon: "h-5 w-5", label: "text-base" },
};

/**
 * Назначение функции: Отображает компонент `Checkbox` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export const Checkbox: React.FC<CheckboxProps> = ({
  checked,
  defaultChecked,
  indeterminate = false,
  size = "md",
  icon = "check",
  label,
  className = "",
  disabled,
  onChange,
  ...rest
}) => {
  const s = SIZE_MAP[size];

  const isControlled = checked !== undefined;
  const [internalChecked, setInternalChecked] =
    React.useState(!!defaultChecked);

  const isChecked = isControlled ? !!checked : internalChecked;

  /**
   * Назначение функции: Обрабатывает данные объекта «результат операции `handleChange`»; операция `handleChange`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!isControlled) {
      setInternalChecked(e.target.checked);
    }
    onChange?.(e);
  };

  return (
    <label
      className={cn(
        "inline-flex select-none items-center gap-2",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        className
      )}
      draggable={false}
    >
      <input
        type="checkbox"
        className="peer sr-only"
        checked={isControlled ? isChecked : undefined}
        defaultChecked={!isControlled ? !!defaultChecked : undefined}
        aria-checked={indeterminate ? "mixed" : isChecked}
        disabled={disabled}
        onChange={handleChange}
        {...rest}
      />

      <span
        className={cn(
          "relative inline-flex items-center justify-center rounded-[var(--radius-sm)] border transition-[background-color,border-color,box-shadow,transform] duration-200 ease-out",
          s.box,
          "border-[color:var(--border)] bg-[color:var(--surface-subtle)]",
          "peer-checked:border-transparent peer-checked:bg-[color:var(--brand)]",
          indeterminate && "border-transparent bg-[color:var(--brand)]",
          !disabled && "active:scale-[0.98]",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-[color:var(--focus-ring-color-strong)] peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[color:var(--focus-ring-offset)]"
        )}
      >
        <IconSVG
          kind={indeterminate ? "minus" : icon}
          className={cn(s.icon, "block shrink-0")}
          visible={isChecked || indeterminate}
        />
      </span>

      {label != null ? (
        <span
          className={cn(
            s.label,
            "align-middle text-[color:var(--text-secondary)]"
          )}
        >
          {label}
        </span>
      ) : null}
    </label>
  );
};

/**
 * Назначение функции: Отображает компонент `IconSVG` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function IconSVG({
  kind,
  className,
  visible,
}: {
  kind: IconKind;
  className?: string;
  visible: boolean;
}) {
  if (!visible) return null;

  if (kind === "dot") {
    return (
      <span
        className={cn("inline-block rounded-[4px]", className)}
        style={{ backgroundColor: "var(--brand-foreground)" }}
      />
    );
  }

  if (kind === "minus") {
    return (
      <svg
        className={cn("block shrink-0", className)}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <line
          x1="5"
          y1="12"
          x2="19"
          y2="12"
          stroke="var(--brand-foreground)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }

  return (
    <svg
      className={cn("block shrink-0", className)}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M5 13l4 4L19 7"
        fill="none"
        stroke="var(--brand-foreground)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
