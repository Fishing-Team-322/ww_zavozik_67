"use client";

import {
  ChangeEvent,
  FocusEvent,
  forwardRef,
  InputHTMLAttributes,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/src/shared/lib/cn";
import { fieldSizeClasses, fieldEndPadding, fieldEndPosition, type FieldSize, fieldLabelClass, fieldHelpClass, fieldErrorClass } from "../field-contract";
import { formatRuDate, parseRuDate } from "@/src/shared/lib/date";

export type DatePickerChangeEvent = {
  target: {
    value: string;
    name?: string;
  };
  currentTarget: {
    value: string;
    name?: string;
  };
};

export interface DatePickerProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "defaultValue" | "onChange"
> {
  inputSize?: FieldSize;
  label?: string;
  helperText?: string;
  error?: string;
  containerClassName?: string;
  value?: string;
  defaultValue?: string;
  onChange?: (event: DatePickerChangeEvent) => void;
  onDateChange?: (date: Date | null) => void;
  minDate?: Date;
  maxDate?: Date;
  weekStartsOn?: 0 | 1;
}

const GAP = 6;
const POPOVER_FALLBACK_HEIGHT = 360;
const MONTH_NAMES = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

const WEEKDAY_LABELS: Record<0 | 1, string[]> = {
  0: ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
  1: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
};

/**
 * Назначение функции: Выполняет операцию `stripToDigits` для объекта «результат операции `stripToDigits`». Возвращает результаты выражений: `value.replace(/\D/g, "").slice(0, 8)`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function stripToDigits(value: string) {
  return value.replace(/\D/g, "").slice(0, 8);
}

/**
 * Назначение функции: Форматирует данные объекта «формат представления»; операция `formatDigitsAsDate`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function formatDigitsAsDate(value: string) {
  const digits = stripToDigits(value);

  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}.${digits.slice(2)}`;

  return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4, 8)}`;
}

const formatDate = formatRuDate;
const parseDate = parseRuDate;

/**
 * Назначение функции: Запускает данные объекта «результат операции `startOfMonth`»; операция `startOfMonth`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function startOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

/**
 * Назначение функции: Добавляет данные объекта «результат операции `addMonths`»; операция `addMonths`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function addMonths(date: Date, amount: number) {
  return new Date(date.getFullYear(), date.getMonth() + amount, 1);
}

/**
 * Назначение функции: Запускает данные объекта «результат операции `startOfWeek`»; операция `startOfWeek`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function startOfWeek(date: Date, weekStartsOn: 0 | 1) {
  const result = new Date(date);
  const day = result.getDay();
  const diff = (day - weekStartsOn + 7) % 7;
  result.setDate(result.getDate() - diff);
  result.setHours(0, 0, 0, 0);
  return result;
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: результат операции `isSameDay`.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function isSameDay(first: Date | null, second: Date | null) {
  if (!first || !second) return false;

  return (
    first.getFullYear() === second.getFullYear() &&
    first.getMonth() === second.getMonth() &&
    first.getDate() === second.getDate()
  );
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: результат операции `isSameMonth`.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function isSameMonth(first: Date, second: Date) {
  return (
    first.getFullYear() === second.getFullYear() &&
    first.getMonth() === second.getMonth()
  );
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: результат операции `isBeforeDay`.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function isBeforeDay(first: Date, second: Date) {
  return (
    new Date(first.getFullYear(), first.getMonth(), first.getDate()).getTime() <
    new Date(
      second.getFullYear(),
      second.getMonth(),
      second.getDate()
    ).getTime()
  );
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: результат операции `isAfterDay`.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function isAfterDay(first: Date, second: Date) {
  return (
    new Date(first.getFullYear(), first.getMonth(), first.getDate()).getTime() >
    new Date(
      second.getFullYear(),
      second.getMonth(),
      second.getDate()
    ).getTime()
  );
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: дата.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function isDateDisabled(date: Date, minDate?: Date, maxDate?: Date) {
  if (minDate && isBeforeDay(date, minDate)) return true;
  if (maxDate && isAfterDay(date, maxDate)) return true;
  return false;
}

/**
 * Назначение функции: Собирает данные объекта «результат операции `buildCalendarDays`»; операция `buildCalendarDays`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function buildCalendarDays(monthDate: Date, weekStartsOn: 0 | 1) {
  const monthStart = startOfMonth(monthDate);
  const gridStart = startOfWeek(monthStart, weekStartsOn);
  const days: Date[] = [];

  for (let index = 0; index < 42; index += 1) {
    const day = new Date(gridStart);
    day.setDate(gridStart.getDate() + index);
    days.push(day);
  }

  return days;
}

/**
 * Назначение функции: Выполняет операцию `focusWithoutScroll` для объекта «результат операции `focusWithoutScroll`». Выполняет вызовы: `element.focus`; значение не возвращает.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function focusWithoutScroll(element: HTMLElement | null) {
  if (!element) return;

  try {
    element.focus({ preventScroll: true });
  } catch {
    element.focus();
  }
}

export const DatePicker = forwardRef<HTMLInputElement, DatePickerProps>(
  /**
   * Назначение функции: Отображает компонент `DatePicker` и связывает его входные данные с JSX-разметкой.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  function DatePicker(
    {
      inputSize = "md",
      className,
      containerClassName,
      label,
      helperText,
      error,
      id,
      disabled,
      name,
      value,
      defaultValue,
      onChange,
      onDateChange,
      onClick,
      onBlur,
      minDate,
      maxDate,
      weekStartsOn = 1,
      ...props
    },
    ref
  ) {
    const generatedId = useId();
    const inputId = id ?? generatedId;

    const [open, setOpen] = useState(false);
    const [internalValue, setInternalValue] = useState(
      String(defaultValue ?? "")
    );
    const [position, setPosition] = useState({ top: 0, left: 0, width: 0 });
    const [openDirection, setOpenDirection] = useState<"up" | "down">("down");
    const [visibleMonth, setVisibleMonth] = useState<Date>(() => {
      const initialDate = parseDate(String(defaultValue ?? ""));
      return startOfMonth(initialDate ?? new Date());
    });

    const rootRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement | null>(null);
    const buttonRef = useRef<HTMLButtonElement | null>(null);
    const popoverRef = useRef<HTMLDivElement | null>(null);

    const currentValue = value != null ? String(value) : internalValue;
    const selectedDate = useMemo(() => parseDate(currentValue), [currentValue]);
    const hasError = Boolean(error);

    const days = useMemo(
      () => buildCalendarDays(visibleMonth, weekStartsOn),
      [visibleMonth, weekStartsOn]
    );

    const weekdayLabels = WEEKDAY_LABELS[weekStartsOn];
    const describedBy = error
      ? `${inputId}-error`
      : helperText
        ? `${inputId}-helper`
        : undefined;

    useEffect(() => {
      if (!selectedDate) return;

      const frame = requestAnimationFrame(() => {
        setVisibleMonth(startOfMonth(selectedDate));
      });

      return () => cancelAnimationFrame(frame);
    }, [selectedDate]);

    /**
     * Назначение функции: Устанавливает данные объекта «поле ввода»; операция `setInputNode`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    function setInputNode(node: HTMLInputElement | null) {
      inputRef.current = node;

      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        ref.current = node;
      }
    }

    /**
     * Назначение функции: Возвращает данные объекта «результат операции `getScrollParents`»; операция `getScrollParents`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    function getScrollParents(node: Element | null): Array<Element | Window> {
      const parents: Array<Element | Window> = [];
      let current: Element | null = node;

      while (current && current !== document.body) {
        const styles = getComputedStyle(current);
        const overflow = `${styles.overflow}${styles.overflowY}${styles.overflowX}`;

        if (/(auto|scroll|overlay)/.test(overflow)) {
          parents.push(current);
        }

        current = current.parentElement;
      }

      parents.push(window);
      return parents;
    }

    /**
     * Назначение функции: Обновляет данные объекта «результат операции `updatePosition`»; операция `updatePosition`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const updatePosition = () => {
      const anchor = rootRef.current;
      if (!anchor) return;

      const anchorRect = anchor.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      const popoverHeight =
        popoverRef.current?.getBoundingClientRect().height ??
        POPOVER_FALLBACK_HEIGHT;

      const spaceBelow = viewportHeight - anchorRect.bottom - GAP;
      const spaceAbove = anchorRect.top - GAP;
      const openUp = spaceBelow < popoverHeight && spaceAbove > spaceBelow;

      setOpenDirection(openUp ? "up" : "down");

      let top = 0;

      if (openUp) {
        top = anchorRect.top - GAP - popoverHeight;
        if (top < GAP) top = GAP;
      } else {
        top = anchorRect.bottom + GAP;
        const maxBottom = viewportHeight - GAP;
        const popoverBottom = top + popoverHeight;

        if (popoverBottom > maxBottom) {
          top -= popoverBottom - maxBottom;
        }
      }

      let left = anchorRect.left;
      const width = Math.max(anchorRect.width, 320);
      const maxLeft = viewportWidth - width - GAP;

      if (left > maxLeft) {
        left = Math.max(GAP, maxLeft);
      }

      setPosition({
        top: Math.round(top),
        left: Math.round(left),
        width: Math.round(width),
      });
    };

    /**
     * Назначение функции: Выполняет операцию `emitValueChange` для объекта «значение». Выполняет вызовы: `setInternalValue`, `onChange`; значение не возвращает.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const emitValueChange = (nextValue: string) => {
      if (value == null) {
        setInternalValue(nextValue);
      }

      onChange?.({
        target: {
          value: nextValue,
          name: name ?? "",
        },
        currentTarget: {
          value: nextValue,
          name: name ?? "",
        },
      });
    };

    /**
     * Назначение функции: Синхронизирует данные объекта «дата»; операция `syncDateChange`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const syncDateChange = (nextValue: string) => {
      const parsed = parseDate(nextValue);

      if (parsed && !isDateDisabled(parsed, minDate, maxDate)) {
        onDateChange?.(parsed);
        setVisibleMonth(startOfMonth(parsed));
      } else {
        onDateChange?.(null);
      }
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «поле ввода»; операция `handleInputChange`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = formatDigitsAsDate(event.target.value);
      emitValueChange(nextValue);
      syncDateChange(nextValue);
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «дата»; операция `handleSelectDate`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleSelectDate = (date: Date) => {
      if (isDateDisabled(date, minDate, maxDate)) return;

      const nextValue = formatDate(date);
      emitValueChange(nextValue);
      onDateChange?.(date);
      setVisibleMonth(startOfMonth(date));
      setOpen(false);

      requestAnimationFrame(() => {
        focusWithoutScroll(inputRef.current);
      });
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «результат операции `handleToggle`»; операция `handleToggle`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleToggle = () => {
      if (disabled) return;

      setOpen((current) => {
        const next = !current;

        if (next) {
          setVisibleMonth(
            startOfMonth(selectedDate ?? parseDate(currentValue) ?? new Date())
          );
        }

        return next;
      });
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «поле ввода»; операция `handleInputBlur`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleInputBlur = (event: FocusEvent<HTMLInputElement>) => {
      onBlur?.(event);
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «поле ввода»; операция `handleInputClick`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleInputClick = (event: React.MouseEvent<HTMLInputElement>) => {
      onClick?.(event);
      if (event.defaultPrevented || disabled || open) return;

      setVisibleMonth(
        startOfMonth(selectedDate ?? parseDate(currentValue) ?? new Date())
      );
      setOpen(true);
    };

    /**
     * Назначение функции: Обрабатывает данные объекта «поле ввода»; операция `handleInputKeyDown`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const handleInputKeyDown = (
      event: React.KeyboardEvent<HTMLInputElement>
    ) => {
      if (disabled) return;

      if (event.key === "ArrowDown") {
        event.preventDefault();
        setOpen(true);
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
    };

    useEffect(() => {
      /**
       * Назначение функции: Обрабатывает данные объекта «результат операции `onMouseDown`»; операция `onMouseDown`.
       * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
       */
      const onMouseDown = (event: MouseEvent) => {
        const target = event.target as Node;
        const clickedInsideRoot = rootRef.current?.contains(target);
        const clickedInsidePopover = popoverRef.current?.contains(target);

        if (!clickedInsideRoot && !clickedInsidePopover) {
          setOpen(false);
        }
      };

      document.addEventListener("mousedown", onMouseDown);
      return () => document.removeEventListener("mousedown", onMouseDown);
    }, []);

    useLayoutEffect(() => {
      if (!open) return;

      const frame = requestAnimationFrame(() => {
        updatePosition();
      });

      const scrollParents = getScrollParents(rootRef.current);
      /**
       * Назначение функции: Обрабатывает данные объекта «результат операции `onScroll`»; операция `onScroll`.
       * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
       */
      const onScroll = () => updatePosition();
      /**
       * Назначение функции: Обрабатывает данные объекта «результат операции `onResize`»; операция `onResize`.
       * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
       */
      const onResize = () => updatePosition();

      scrollParents.forEach((parent) => {
        parent.addEventListener("scroll", onScroll as EventListener, {
          passive: true,
        });
      });

      window.addEventListener("resize", onResize);

      return () => {
        window.cancelAnimationFrame(frame);

        scrollParents.forEach((parent) => {
          parent.removeEventListener("scroll", onScroll as EventListener);
        });

        window.removeEventListener("resize", onResize);
      };
    }, [open]);

    useLayoutEffect(() => {
      if (!open) return;

      const frame = requestAnimationFrame(() => {
        updatePosition();
      });

      return () => {
        window.cancelAnimationFrame(frame);
      };
    }, [open, visibleMonth]);

    const popover =
      open && !disabled && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={popoverRef}
              role="dialog"
              aria-label={label ?? "Выбор даты"}
              className={cn(
                "overflow-hidden rounded-[10px] border border-[color:var(--border)] bg-[color:var(--surface)] shadow-[var(--shadow-lg)]",
                openDirection === "up"
                  ? "[animation:datePickerOpenUp_180ms_cubic-bezier(0.22,1,0.36,1)]"
                  : "[animation:datePickerOpenDown_180ms_cubic-bezier(0.22,1,0.36,1)]"
              )}
              style={{
                position: "fixed",
                top: position.top,
                left: position.left,
                width: position.width,
                zIndex: 10000,
                transformOrigin:
                  openDirection === "up" ? "bottom center" : "top center",
              }}
            >
              <div className="border-b border-[color:var(--border)] px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <button
                    type="button"
                    onClick={() =>
                      setVisibleMonth((prev) => addMonths(prev, -1))
                    }
                    className={cn(
                      "inline-flex h-9 w-9 items-center justify-center rounded-[10px] text-[color:var(--muted-foreground)] transition-colors",
                      "hover:bg-[color:var(--surface-subtle)] hover:text-[color:var(--foreground)]",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    )}
                  >
                    <ChevronLeftIcon className="h-5 w-5" />
                  </button>

                  <div className="text-base font-medium text-[color:var(--foreground)]">
                    {MONTH_NAMES[visibleMonth.getMonth()]}{" "}
                    {visibleMonth.getFullYear()}
                  </div>

                  <button
                    type="button"
                    onClick={() =>
                      setVisibleMonth((prev) => addMonths(prev, 1))
                    }
                    className={cn(
                      "inline-flex h-9 w-9 items-center justify-center rounded-[10px] text-[color:var(--muted-foreground)] transition-colors",
                      "hover:bg-[color:var(--surface-subtle)] hover:text-[color:var(--foreground)]",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    )}
                  >
                    <ChevronRightIcon className="h-5 w-5" />
                  </button>
                </div>
              </div>

              <div className="px-4 pb-4 pt-3">
                <div className="mb-2 grid grid-cols-7 gap-1">
                  {weekdayLabels.map((weekday) => (
                    <div
                      key={weekday}
                      className="flex h-9 items-center justify-center text-xs font-medium uppercase tracking-[0.06em] text-[color:var(--muted-foreground)]"
                    >
                      {weekday}
                    </div>
                  ))}
                </div>

                <div className="grid grid-cols-7 gap-1">
                  {days.map((day) => {
                    const outsideCurrentMonth = !isSameMonth(day, visibleMonth);
                    const isSelected = isSameDay(day, selectedDate);
                    const isToday = isSameDay(day, new Date());
                    const isDisabled = isDateDisabled(day, minDate, maxDate);

                    return (
                      <button
                        key={day.toISOString()}
                        type="button"
                        disabled={isDisabled}
                        onClick={() => handleSelectDate(day)}
                        className={cn(
                          "inline-flex h-10 items-center justify-center rounded-[10px] text-sm font-medium transition-colors",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                          isDisabled
                            ? "cursor-not-allowed opacity-35"
                            : "hover:bg-[color:var(--surface-subtle)]",
                          outsideCurrentMonth
                            ? "text-[color:var(--muted-foreground)]"
                            : "text-[color:var(--foreground)]",
                          isToday &&
                            !isSelected &&
                            "border border-[color:var(--input-border-hover)]",
                          isSelected &&
                            "bg-[color:var(--accent)] text-[color:var(--accent-foreground)] hover:bg-[color:var(--accent-hover)]"
                        )}
                      >
                        {day.getDate()}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-4 flex items-center justify-between gap-3 border-t border-[color:var(--border)] pt-3">
                  <button
                    type="button"
                    onClick={() => {
                      const today = new Date();
                      handleSelectDate(today);
                    }}
                    className={cn(
                      "inline-flex h-9 items-center justify-center rounded-[10px] px-3 text-sm font-medium",
                      "text-[color:var(--foreground)] transition-colors hover:bg-[color:var(--surface-subtle)]",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    )}
                  >
                    Сегодня
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      emitValueChange("");
                      onDateChange?.(null);
                      setOpen(false);

                      requestAnimationFrame(() => {
                        focusWithoutScroll(inputRef.current);
                      });
                    }}
                    className={cn(
                      "inline-flex h-9 items-center justify-center rounded-[10px] px-3 text-sm font-medium",
                      "text-[color:var(--muted-foreground)] transition-colors hover:bg-[color:var(--surface-subtle)] hover:text-[color:var(--foreground)]",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                    )}
                  >
                    Очистить
                  </button>
                </div>
              </div>
            </div>,
            document.body
          )
        : null;

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

        <div ref={rootRef} className="relative">
          <input
            ref={setInputNode}
            id={inputId}
            type="text"
            name={name}
            value={currentValue}
            disabled={disabled}
            inputMode="numeric"
            autoComplete="off"
            maxLength={10}
            aria-invalid={hasError}
            aria-describedby={describedBy}
            placeholder="ДД.ММ.ГГГГ"
            onChange={handleInputChange}
            onClick={handleInputClick}
            onBlur={handleInputBlur}
            onKeyDown={handleInputKeyDown}
            className={cn(
              "block w-full appearance-none rounded-[6px] border bg-[var(--input-background)] outline-none touch-manipulation",
              "cursor-text font-normal text-[color:var(--input-text)] placeholder:text-[color:var(--input-placeholder)]",
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
                    "hover:bg-[var(--input-background-hover)]",
                    "focus:border-[color:var(--input-border-focus)]",
                    "focus:bg-[var(--input-background-focus)]",
                    "focus:ring-[3px] focus:ring-[color:var(--focus-ring)]",
                    "focus:shadow-[0_0_0_1px_var(--input-border-focus)]",
                  ].join(" "),
              fieldSizeClasses[inputSize],
              fieldEndPadding[inputSize],
              className
            )}
            {...props}
          />

          <button
            ref={buttonRef}
            type="button"
            disabled={disabled}
            aria-label="Открыть календарь"
            onMouseDown={(event) => {
              event.preventDefault();
            }}
            onClick={handleToggle}
            className={cn(
              "absolute top-1/2 z-20 inline-flex -translate-y-1/2 items-center justify-center rounded-md",
              "text-[color:var(--text-muted)] transition-[background-color,color] duration-150",
              "hover:bg-[var(--surface-subtle)] hover:text-[color:var(--text-secondary)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--focus-ring-offset)]",
              "disabled:cursor-not-allowed disabled:opacity-50",
              fieldEndPosition[inputSize]
            )}
          >
            <CalendarIcon className="h-4 w-4" />
          </button>

          {popover}
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

        <style jsx>{`
          @keyframes datePickerOpenDown {
            from {
              opacity: 0;
              transform: translateY(-8px) scale(0.98);
            }
            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }

          @keyframes datePickerOpenUp {
            from {
              opacity: 0;
              transform: translateY(8px) scale(0.98);
            }
            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }
        `}</style>
      </div>
    );
  }
);

DatePicker.displayName = "DatePicker";

/**
 * Назначение функции: Отображает компонент `CalendarIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function CalendarIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M7 3V6M17 3V6M4 9H20M6 5H18C19.1046 5 20 5.89543 20 7V19C20 20.1046 19.1046 21 18 21H6C4.89543 21 4 20.1046 4 19V7C4 5.89543 4.89543 5 6 5Z"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Отображает компонент `ChevronLeftIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function ChevronLeftIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M12.5 4.5L7 10L12.5 15.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Отображает компонент `ChevronRightIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function ChevronRightIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className={className}
      aria-hidden="true"
    >
      <path
        d="M7.5 4.5L13 10L7.5 15.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export const DateField = DatePicker;
