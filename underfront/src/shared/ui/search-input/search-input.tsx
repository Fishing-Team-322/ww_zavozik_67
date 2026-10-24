"use client";

import { Loader2, Search } from "lucide-react";

import { cn } from "@/src/shared/lib/cn";
import { Input, type InputProps } from "@/src/shared/ui/input";

export interface SearchInputProps
  extends Omit<InputProps, "type" | "startAdornment"> {
  loading?: boolean;
  label?: string;
}

const loaderSize = {
  sm: 12,
  md: 12,
  lg: 12,
} as const;

const loaderPosition = {
  sm: {
    withLabel: "right-1 top-7",
    withoutLabel: "right-1 top-2.5",
  },
  md: {
    withLabel: "right-1.5 top-[30px]",
    withoutLabel: "right-1.5 top-3",
  },
  lg: {
    withLabel: "right-3 top-[34px]",
    withoutLabel: "right-3 top-4",
  },
} as const;

const loaderPadding = {
  sm: "pr-6",
  md: "pr-7",
  lg: "pr-9",
} as const;

/**
 * Назначение функции: Отображает компонент `SearchInput` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function SearchInput({
  className,
  containerClassName,
  loading = false,
  disabled,
  inputSize = "md",
  label,
  ...props
}: SearchInputProps) {
  return (
    <div className="relative w-full">
      <Input
        type="search"
        inputSize={inputSize}
        label={label}
        disabled={disabled || loading}
        startAdornment={<Search size={12} strokeWidth={2} />}
        containerClassName={containerClassName}
        className={cn(loading && loaderPadding[inputSize], className)}
        {...props}
      />

      {loading ? (
        <Loader2
          size={loaderSize[inputSize]}
          strokeWidth={2.25}
          className={cn(
            "pointer-events-none absolute z-10 -translate-y-1/2 animate-spin text-[color:var(--text-muted)]",
            label
              ? loaderPosition[inputSize].withLabel
              : loaderPosition[inputSize].withoutLabel
          )}
        />
      ) : null}
    </div>
  );
}
