"use client";

import {
  forwardRef,
  ReactNode,
  TextareaHTMLAttributes,
  useId,
} from "react";
import { cn } from "@/src/shared/lib/cn";
import { fieldTextClass, fieldLabelClass, fieldHelpClass, fieldErrorClass } from "../field-contract";

type ControlSize = "sm" | "md" | "lg";

export interface TextareaProps
  extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  size?: ControlSize;
  textareaSize?: ControlSize;
  label?: string;
  helperText?: string;
  error?: string;
  containerClassName?: string;
  startAdornment?: ReactNode;
  startAdornmentClassName?: string;
}

const sizeClasses: Record<ControlSize, string> = {
  sm: "min-h-20 max-h-48 px-2 py-2",
  md: "min-h-24 max-h-56 px-3 py-2.5",
  lg: "min-h-32 max-h-64 px-4 py-3",
};

const sizeClassesWithStartAdornment: Record<ControlSize, string> = {
  sm: "pl-7",
  md: "pl-9",
  lg: "pl-10",
};

const adornmentPositionClasses: Record<ControlSize, string> = {
  sm: "left-2 top-2",
  md: "left-3 top-2.5",
  lg: "left-4 top-3",
};

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  /**
   * Назначение функции: Отображает компонент `Textarea` и связывает его входные данные с JSX-разметкой.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  function Textarea(
    {
      className,
      containerClassName,
      size,
      textareaSize = "md",
      label,
      helperText,
      error,
      id,
      disabled,
      startAdornment,
      startAdornmentClassName,
      ...props
    },
    ref
  ) {
    const resolvedSize = size ?? textareaSize;

    const generatedId = useId();
    const textareaId = id ?? generatedId;

    const hasStartAdornment = Boolean(startAdornment);
    const hasError = Boolean(error);

    const describedBy = error
      ? `${textareaId}-error`
      : helperText
        ? `${textareaId}-helper`
        : undefined;

    return (
      <div className={cn("w-full", containerClassName)}>
        {label ? (
          <label
            htmlFor={textareaId}
            className={cn(
              fieldLabelClass,
              hasError
                ? "text-[var(--status-danger-fg)]"
                : "text-[color:var(--input-label)]"
            )}
          >
            {label}
          </label>
        ) : null}

        <div className="relative">
          {hasStartAdornment ? (
            <div
              className={cn(
                "pointer-events-none absolute z-10 text-[color:var(--text-muted)]",
                adornmentPositionClasses[resolvedSize],
                startAdornmentClassName
              )}
              aria-hidden="true"
            >
              {startAdornment}
            </div>
          ) : null}

          <textarea
            ref={ref}
            id={textareaId}
            disabled={disabled}
            aria-invalid={hasError}
            aria-describedby={describedBy}
            className={cn(
              "block w-full appearance-none resize-y rounded-[6px] border bg-[var(--input-background)] outline-none touch-manipulation",
              "font-normal text-[color:var(--input-text)] placeholder:text-[color:var(--input-placeholder)]",
              "shadow-none transition-[background,border,box-shadow,color] duration-150 ease-[ease]",
              "disabled:cursor-not-allowed disabled:bg-[var(--input-disabled-bg)] disabled:text-[color:var(--input-disabled-fg)] disabled:opacity-70",
              hasError
                ? [
                    "border-[var(--status-danger-border)]",
                    "focus:border-[var(--status-danger-border)]",
                    "focus:ring-[3px] focus:ring-[color:var(--status-danger-ring)]",
                    "focus:shadow-[0_0_0_1px_var(--status-danger-border)]",
                  ].join(" ")
                : [
                    "border-[color:var(--input-border)]",
                    "hover:border-[color:var(--input-border-hover)]",
                    "focus:border-[color:var(--input-border-focus)]",
                    "focus:ring-[3px] focus:ring-[color:var(--focus-ring)]",
                    "focus:shadow-[0_0_0_1px_var(--input-border-focus)]",
                  ].join(" "),
              fieldTextClass,
              sizeClasses[resolvedSize],
              hasStartAdornment
                ? sizeClassesWithStartAdornment[resolvedSize]
                : undefined,
              className
            )}
            {...props}
          />
        </div>

        {error ? (
          <p
            id={`${textareaId}-error`}
            className={fieldErrorClass}
          >
            {error}
          </p>
        ) : helperText ? (
          <p
            id={`${textareaId}-helper`}
            className={fieldHelpClass}
          >
            {helperText}
          </p>
        ) : null}
      </div>
    );
  }
);

Textarea.displayName = "Textarea";
