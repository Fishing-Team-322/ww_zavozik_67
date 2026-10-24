"use client";

import { cn } from "@/src/shared/lib/cn";
import { DateField } from "./date-field";

export type DateRangeFieldProps = {
  fromValue: string;
  toValue: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  fromLabel?: string;
  toLabel?: string;
  containerClassName?: string;
  minDate?: Date;
  maxDate?: Date;
  disabled?: boolean;
};

/**
 * Two `DateField`s composed into a from/to range. There is no dedicated
 * range-picker component in the design system yet, so this reuses the single
 * date popover twice rather than inventing a new visual language.
 */
/**
 * Назначение функции: Two `DateField`s composed into a from/to range. There is no dedicated range-picker component in the design system yet, so this reuses the single date popover twice rather than inventing a new visual language.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function DateRangeField({
  fromValue,
  toValue,
  onFromChange,
  onToChange,
  fromLabel = "С",
  toLabel = "По",
  containerClassName,
  minDate,
  maxDate,
  disabled,
}: DateRangeFieldProps) {
  return (
    <div className={cn("grid grid-cols-2 gap-3", containerClassName)}>
      <DateField
        label={fromLabel}
        value={fromValue}
        disabled={disabled}
        minDate={minDate}
        maxDate={maxDate}
        onChange={(event) => onFromChange(event.target.value)}
      />

      <DateField
        label={toLabel}
        value={toValue}
        disabled={disabled}
        minDate={minDate}
        maxDate={maxDate}
        onChange={(event) => onToChange(event.target.value)}
      />
    </div>
  );
}
