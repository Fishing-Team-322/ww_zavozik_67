"use client";

import {
  forwardRef,
  InputHTMLAttributes,
  ReactNode,
  useId,
  useState,
} from "react";
import { cn } from "@/src/shared/lib/cn";
import { fieldSizeClasses, fieldEndPosition, fieldLabelClass, fieldHelpClass, fieldErrorClass } from "../field-contract";

type SecretToggleLabels = {
  show: string;
  hide: string;
};

/**
 * Назначение функции: Собирает данные объекта «результат операции `buildDefaultPlaceholder`»; операция `buildDefaultPlaceholder`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function buildDefaultPlaceholder(
  label: string | undefined,
  type: InputHTMLAttributes<HTMLInputElement>["type"]
) {
  const normalized = label?.trim().toLowerCase() ?? "";

  if (!normalized) {
    if (type === "email") return "name@company.ru";
    if (type === "tel") return "+7 (___) ___-__-__";
    if (type === "password") return "Введите пароль";
    return undefined;
  }

  if (type === "password" || normalized.includes("парол")) {
    return "Введите пароль";
  }

  if (type === "email" || normalized.includes("e-mail") || normalized.includes("email")) {
    return "name@company.ru";
  }

  if (type === "tel" || normalized.includes("телефон")) {
    return "+7 (___) ___-__-__";
  }

  if (normalized.includes("инн")) return "7701234567";
  if (normalized.includes("кпп")) return "770101001";
  if (normalized.includes("огрн")) return "1027700132195";
  if (normalized.includes("vin")) return "XTA210990Y1234567";
  if (normalized.includes("госномер")) return "А123АА 777";
  if (normalized.includes("юридическое название")) return "ООО ТрансЛогистика";
  if (normalized.includes("бренд")) return "ТрансЛогистика";
  if (normalized.includes("адрес")) return "г. Москва, ул. Пример, д. 10";
  if (normalized.includes("регионы")) return "Москва, Московская область";
  if (normalized.includes("регион отправления")) return "Москва";
  if (normalized.includes("регион назначения")) return "Казань";
  if (normalized.includes("город отправления")) return "Москва";
  if (normalized.includes("город назначения")) return "Казань";
  if (normalized.includes("название предложения")) return "Свободная фура Москва -> Казань";
  if (normalized.includes("цена") || normalized.includes("сумма")) return "100000";
  if (normalized.includes("грузоподъёмность")) return "20000";
  if (normalized.includes("объём")) return "82";
  if (normalized.includes("доступен с")) return "Выберите дату";
  if (normalized.includes("доступен до")) return "Выберите дату";
  if (normalized.includes("дата")) return "Выберите дату";

  return `Введите ${normalized}`;
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  inputSize?: "sm" | "md" | "lg";
  label?: string;
  helperText?: string;
  error?: string;
  containerClassName?: string;
  startAdornment?: ReactNode;
  endAdornment?: ReactNode;
  startAdornmentClassName?: string;
  secretToggle?: boolean;
  secretToggleLabels?: SecretToggleLabels;
}

const sizeClasses = fieldSizeClasses;

const sizeClassesWithStartAdornment: Record<
  NonNullable<InputProps["inputSize"]>,
  string
> = {
  sm: "pl-7",
  md: "pl-9",
  lg: "pl-10",
};

const sizeClassesWithEndControl: Record<
  NonNullable<InputProps["inputSize"]>,
  string
> = {
  sm: "pr-9",
  md: "pr-10",
  lg: "pr-11",
};

const adornmentPositionClasses: Record<
  NonNullable<InputProps["inputSize"]>,
  string
> = {
  sm: "left-2 top-1/2 -translate-y-1/2",
  md: "left-3 top-1/2 -translate-y-1/2",
  lg: "left-4 top-1/2 -translate-y-1/2",
};

const secretTogglePositionClasses: Record<NonNullable<InputProps["inputSize"]>, string> = {
  sm: "right-1.5 h-6 w-6",
  md: "right-2 h-6 w-6",
  lg: "right-2.5 h-7 w-7",
};

/**
 * Назначение функции: Отображает компонент `SecretEyeIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function SecretEyeIcon({
  revealed,
  className,
}: {
  revealed: boolean;
  className?: string;
}) {
  if (revealed) {
    return (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className={className ?? "h-5 w-5"}
      >
        <path
          d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className ?? "h-5 w-5"}
    >
      <path
        d="M3 3l18 18"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path
        d="M10.58 10.58A2 2 0 0 0 13.42 13.42"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9.88 5.18A10.64 10.64 0 0 1 12 5c6 0 9.5 7 9.5 7a16.8 16.8 0 0 1-2.08 2.95"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M6.6 6.6C4.05 8.32 2.5 12 2.5 12s3.5 7 9.5 7c1.98 0 3.68-.56 5.08-1.36"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export const Input = forwardRef<HTMLInputElement, InputProps>(/**
 * Назначение функции: Отображает компонент `Input` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function Input(
  {
    className,
    containerClassName,
    inputSize = "md",
    label,
    helperText,
    error,
    id,
    disabled,
    startAdornment,
    endAdornment,
    startAdornmentClassName,
    secretToggle = false,
    secretToggleLabels = {
      show: "Показать значение",
      hide: "Скрыть значение",
    },
    type = "text",
    placeholder,
    ...props
  },
  ref
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;

  const [isSecretVisible, setIsSecretVisible] = useState(false);

  const hasStartAdornment = Boolean(startAdornment);
  const hasError = Boolean(error);
  const hasSecretToggle = Boolean(secretToggle);
  const resolvedPlaceholder = placeholder ?? buildDefaultPlaceholder(label, type);

  const describedBy = error
    ? `${inputId}-error`
    : helperText
      ? `${inputId}-helper`
      : undefined;

  const resolvedType = hasSecretToggle
    ? isSecretVisible
      ? "text"
      : "password"
    : type;

  return (
    <div className={cn("w-full", containerClassName)}>
      {label ? (
        <label
          htmlFor={inputId}
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
              "pointer-events-none absolute z-10 text-[color:var(--text-muted)] [&>svg]:h-4 [&>svg]:w-4",
              adornmentPositionClasses[inputSize],
              startAdornmentClassName
            )}
            aria-hidden="true"
          >
            {startAdornment}
          </div>
        ) : null}

        <input
          ref={ref}
          id={inputId}
          type={resolvedType}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          aria-invalid={hasError}
          aria-describedby={describedBy}
          className={cn(
            "block w-full appearance-none rounded-[6px] border bg-[var(--input-background)] outline-none touch-manipulation",
            "cursor-text text-[color:var(--input-text)] placeholder:text-[color:var(--input-placeholder)]",
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
            sizeClasses[inputSize],
            hasStartAdornment
              ? sizeClassesWithStartAdornment[inputSize]
              : undefined,
            hasSecretToggle || endAdornment ? sizeClassesWithEndControl[inputSize] : undefined,
            className
          )}
          {...props}
        />

        {endAdornment && !hasSecretToggle ? (
          <span aria-hidden="true" className={cn("pointer-events-none absolute top-1/2 inline-flex -translate-y-1/2 items-center justify-center text-[color:var(--text-muted)]", fieldEndPosition[inputSize])}>
            {endAdornment}
          </span>
        ) : null}

        {hasSecretToggle ? (
          <button
            type="button"
            disabled={disabled}
            aria-label={
              isSecretVisible
                ? secretToggleLabels.hide
                : secretToggleLabels.show
            }
            aria-pressed={isSecretVisible}
            title={
              isSecretVisible
                ? secretToggleLabels.hide
                : secretToggleLabels.show
            }
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            onClick={() => {
              setIsSecretVisible((prev) => !prev);
            }}
            className={cn(
              "absolute top-1/2 z-20 inline-flex -translate-y-1/2 items-center justify-center rounded-[4px]",
              secretTogglePositionClasses[inputSize],
              "text-[color:var(--text-muted)] transition-colors duration-150",
              "hover:text-[color:var(--text-secondary)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--focus-ring-offset)]",
              "disabled:cursor-not-allowed disabled:opacity-50"
            )}
          >
            <SecretEyeIcon revealed={isSecretVisible} className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      {error ? (
        <p
          id={`${inputId}-error`}
          className={fieldErrorClass}
        >
          {error}
        </p>
      ) : helperText ? (
        <p
          id={`${inputId}-helper`}
          className={fieldHelpClass}
        >
          {helperText}
        </p>
      ) : null}
    </div>
  );
});

Input.displayName = "Input";
