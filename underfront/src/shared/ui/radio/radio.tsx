"use client";

import React from "react";
import { cn } from "@/src/shared/lib/cn";

export interface RadioOption {
  label: React.ReactNode;
  value: string;
  disabled?: boolean;
}

interface RadioGroupProps {
  options: RadioOption[];
  value: string;
  onChange: (value: string) => void;
  name: string;
  className?: string;
}

export interface RadioProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type"
> {
  label?: React.ReactNode;
}

/**
 * Назначение функции: Отображает компонент `Radio` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Radio({ className, label, disabled, ...props }: RadioProps) {
  return (
    <label
      className={cn(
        "inline-flex items-center gap-2 select-none",
        disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
        className
      )}
      onMouseDown={(event) => event.preventDefault()}
      draggable={false}
    >
      <input
        type="radio"
        className="peer sr-only"
        disabled={disabled}
        {...props}
      />
      <span
        className={cn(
          "h-5 w-5 rounded-full border bg-[color:var(--surface-subtle)] transition-[border-color,box-shadow,transform] duration-200 ease-out",
          "border-[color:var(--border)]",
          "peer-checked:border-[color:var(--brand)]",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-[color:var(--focus-ring-color-strong)] peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[color:var(--focus-ring-offset)]"
        )}
        aria-hidden
      >
        <span className="m-auto mt-[4px] block h-2.5 w-2.5 rounded-full bg-[color:var(--brand)] opacity-0 scale-75 transition-all duration-150 ease-out peer-checked:scale-100 peer-checked:opacity-100" />
      </span>
      {label ? (
        <span className="text-sm text-[color:var(--text-primary)]">
          {label}
        </span>
      ) : null}
    </label>
  );
}

/**
 * Назначение функции: Отображает компонент `RadioGroup` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export const RadioGroup: React.FC<RadioGroupProps> = ({
  options,
  value,
  onChange,
  name,
  className,
}) => {
  return (
    <div className={cn("flex flex-wrap gap-4", className)} role="radiogroup">
      {options.map((option) => {
        const checked = value === option.value;
        const disabled = !!option.disabled;

        return (
          <label
            key={option.value}
            htmlFor={`${name}-${option.value}`}
            className={cn(
              "inline-flex select-none items-center gap-2",
              disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"
            )}
            onMouseDown={(event) => event.preventDefault()}
            draggable={false}
          >
            <input
              type="radio"
              id={`${name}-${option.value}`}
              name={name}
              value={option.value}
              checked={checked}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
              disabled={disabled}
            />

            <span
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full border bg-[color:var(--surface-subtle)] transition-[border-color,box-shadow,transform] duration-200 ease-out",
                checked
                  ? "border-[color:var(--brand)]"
                  : "border-[color:var(--border)]",
                "peer-focus-visible:ring-2 peer-focus-visible:ring-[color:var(--focus-ring-color-strong)] peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-[color:var(--focus-ring-offset)]"
              )}
              aria-hidden="true"
            >
              {checked && (
                <span className="block h-2.5 w-2.5 animate-radio-in rounded-full bg-[color:var(--brand)]" />
              )}
            </span>

            <span
              className={cn(
                "text-sm font-medium",
                checked
                  ? "text-[color:var(--text-primary)]"
                  : "text-[color:var(--text-secondary)]"
              )}
            >
              {option.label}
            </span>
          </label>
        );
      })}
    </div>
  );
};
