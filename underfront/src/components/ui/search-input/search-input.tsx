"use client";

import { Loader2, Search } from "lucide-react";

import { cn } from "@/src/lib/cn";
import { Input, type InputProps } from "@/src/components/ui/input";

export interface SearchInputProps
  extends Omit<InputProps, "type" | "startAdornment"> {
  loading?: boolean;
  label?: string;
}

const loaderSize = {
  sm: 20,
  md: 22,
  lg: 24,
} as const;

const loaderPosition = {
  sm: {
    withLabel: "right-3 top-9",
    withoutLabel: "right-3 top-[18px]",
  },
  md: {
    withLabel: "right-3.5 top-10",
    withoutLabel: "right-3.5 top-[22px]",
  },
  lg: {
    withLabel: "right-4 top-[42px]",
    withoutLabel: "right-4 top-6",
  },
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
        startAdornment={<Search size={20} strokeWidth={2} />}
        containerClassName={containerClassName}
        className={cn(loading && "pr-12", className)}
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
