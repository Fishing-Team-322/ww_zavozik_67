"use client";

import {
  ChangeEvent,
  Children,
  FocusEvent,
  KeyboardEvent,
  ReactElement,
  ReactNode,
  SelectHTMLAttributes,
  forwardRef,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/src/shared/lib/cn";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export type SelectChangeEvent = ChangeEvent<HTMLSelectElement>;

export interface SelectProps extends Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "onChange" | "size"
> {
  size?: "sm" | "md" | "lg";
  fitContent?: boolean;
  options?: SelectOption[];
  label?: string;
  helperText?: string;
  error?: string;
  containerClassName?: string;
  placeholder?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  onEmptyAction?: () => void;
  emptyActionLabel?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  onChange?: (event: SelectChangeEvent) => void;
  children?: ReactNode;
  triggerClassName?: string;
  renderOption?: (option: SelectOption, selected: boolean) => ReactNode;
}

const GAP = 8;
const DROPDOWN_MIN_WIDTH = 280;
const DROPDOWN_FALLBACK_HEIGHT = 320;
const triggerSizeClasses = {
  sm: "h-5 rounded-[6px] pl-1 pr-5",
  md: "h-6 rounded-[6px] pl-1.5 pr-6",
  lg: "h-10 rounded-[6px] pl-3 pr-7",
} as const;
const chevronPositionClasses = {
  sm: "right-1",
  md: "right-1.5",
  lg: "right-2.5",
} as const;
const optionSizeClasses = {
  sm: "h-5 rounded-[5px] px-1 text-xs font-medium leading-4 tabular-nums",
  md: "h-6 rounded-[6px] px-1.5 text-xs font-medium leading-4 tabular-nums",
  lg: "h-8 rounded-[6px] px-3 text-sm font-medium leading-5 tabular-nums",
} as const;

/**
 * Назначение функции: Собирает данные объекта «результат операции `buildDefaultSelectPlaceholder`»; операция `buildDefaultSelectPlaceholder`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function buildDefaultSelectPlaceholder(label?: string) {
  const normalized = label?.trim().toLowerCase() ?? "";

  if (!normalized) return "Выберите значение";
  if (normalized.includes("тип"))
    return `Выберите ${label?.trim().toLowerCase()}`;
  if (normalized.includes("формат")) return "Выберите формат";
  if (normalized.includes("статус")) return "Выберите статус";
  if (normalized.includes("этап")) return "Выберите этап";
  if (normalized.includes("решение")) return "Выберите решение";
  if (normalized.includes("профиль")) return "Выберите профиль";
  if (normalized.includes("документ")) return "Выберите документ";

  return `Выберите ${normalized}`;
}

/**
 * Назначение функции: Возвращает данные объекта «результат операции `getInitialActiveIndex`»; операция `getInitialActiveIndex`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function getInitialActiveIndex(
  options: ReadonlyArray<SelectOption>,
  value: string
): number | null {
  const selectedIndex = options.findIndex(
    (option) => option.value === value && !option.disabled
  );

  if (selectedIndex >= 0) return selectedIndex;

  const firstEnabledIndex = options.findIndex((option) => !option.disabled);
  return firstEnabledIndex >= 0 ? firstEnabledIndex : null;
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

export const Select = forwardRef<HTMLSelectElement, SelectProps> (/**
 * Назначение функции: Показывает выбор значения с поиском, клавиатурным управлением и адаптивным меню; различает пустой допустимый вариант и placeholder.
 * Зачем используется: Даёт формам единый доступный выбор с нативным select, понятной подписью кнопки и корректной семантикой корневого или отсутствующего значения.
 */
function Select(
  {
    value,
    defaultValue,
    onChange,
    options,
    children,
    label,
    helperText,
    error,
    containerClassName,
    placeholder,
    size,
    fitContent = false,
    className,
    triggerClassName,
    searchable = false,
    searchPlaceholder = "Поиск...",
    onEmptyAction,
    emptyActionLabel = "Очистить поиск",
    emptyTitle = "Ничего не найдено",
    emptyDescription = "Попробуйте изменить запрос или выбрать другой вариант",
    disabled,
    name,
    id,
    onBlur,
    "aria-label": ariaLabel,
    renderOption,
    ...props
  },
  ref
) {
  const reactId = useId();
  const inputId = id ?? `select-${reactId.replace(/:/g, "")}`;
  const triggerId = `${inputId}-trigger`;

  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [internalValue, setInternalValue] = useState(
    String(defaultValue ?? "")
  );
  const [position, setPosition] = useState({ top: 0, left: 0, width: 0 });
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [openDirection, setOpenDirection] = useState<"up" | "down">("down");

  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const currentValue = value != null ? String(value) : internalValue;
  const resolvedPlaceholder =
    placeholder ?? buildDefaultSelectPlaceholder(label);
  const hasError = Boolean(error);

  const normalizedOptions = useMemo(() => {
    if (options?.length) return options;

    return Children.toArray(children)
      .filter(
        (
          child
        ): child is ReactElement<{
          value?: string;
          disabled?: boolean;
          children?: ReactNode;
        }> => isValidElement(child)
      )
      .map((child) => {
        const childValue = child.props.value;
        const childLabel =
          typeof child.props.children === "string"
            ? child.props.children
            : String(child.props.children ?? childValue ?? "");

        return {
          value: String(childValue ?? ""),
          label: childLabel,
          disabled: Boolean(child.props.disabled),
        };
      });
  }, [children, options]);

  const selected = normalizedOptions.find(
    (option) => option.value === currentValue
  );

  const hasPlaceholderOption = normalizedOptions.some(
    (option) => option.value === ""
  );

  const filteredOptions =
    searchable && search.trim()
      ? normalizedOptions.filter((option) => {
          const query = search.trim().toLowerCase();

          return (
            option.label.toLowerCase().includes(query) ||
            option.value.toLowerCase().includes(query)
          );
        })
      : normalizedOptions;

  // Явный разрешённый вариант «без родителя/без бюджета» с пустым value — настоящий выбор; disabled пустой вариант остаётся подсказкой.
  const hasValue =
    (selected != null && !selected.disabled) ||
    (currentValue !== "" && currentValue != null);

  const displayValue = hasValue
    ? (selected?.label ?? currentValue)
    : resolvedPlaceholder;

  const triggerAriaLabel =
    ariaLabel ??
    label ??
    (selected
      ? `Выбрано: ${selected.label}`
      : resolvedPlaceholder || "Открыть список");

  const menuAriaLabel =
    ariaLabel ?? label ?? resolvedPlaceholder ?? "Список выбора";

  const initialActiveIndex = getInitialActiveIndex(
    filteredOptions,
    currentValue
  );

  const updatePosition = useCallback(() => {
    const button = buttonRef.current;
    if (!button) return;

    const buttonRect = button.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;
    const listHeight =
      listRef.current?.getBoundingClientRect().height ??
      DROPDOWN_FALLBACK_HEIGHT;

    const menuWidth = Math.min(
      viewportWidth - GAP * 2,
      size
        ? Math.max(buttonRect.width + 12, fitContent ? 128 : 172)
        : Math.max(buttonRect.width, DROPDOWN_MIN_WIDTH)
    );

    const spaceBelow = viewportHeight - buttonRect.bottom - GAP;
    const spaceAbove = buttonRect.top - GAP;
    const openUp = spaceBelow < listHeight && spaceAbove > spaceBelow;

    setOpenDirection(openUp ? "up" : "down");

    let top = 0;

    if (openUp) {
      top = buttonRect.top - GAP - listHeight;
      if (top < GAP) top = GAP;
    } else {
      top = buttonRect.bottom + GAP;
      const maxBottom = viewportHeight - GAP;
      const dropdownBottom = top + listHeight;

      if (dropdownBottom > maxBottom) {
        top -= dropdownBottom - maxBottom;
      }
    }

    let left = buttonRect.left;
    const maxLeft = viewportWidth - menuWidth - GAP;

    if (left > maxLeft) {
      left = Math.max(GAP, maxLeft);
    }

    setPosition({
      top: Math.round(top),
      left: Math.round(left),
      width: Math.round(menuWidth),
    });
  }, [size, fitContent]);

  /**
   * Назначение функции: Выполняет операцию `emitChange` для объекта «результат операции `emitChange`». Выполняет вызовы: `setInternalValue`, `onChange`; значение не возвращает.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const emitChange = (nextValue: string) => {
    if (value == null) {
      setInternalValue(nextValue);
    }

    onChange?.({
      target: { value: nextValue, name: name ?? "" },
      currentTarget: { value: nextValue, name: name ?? "" },
    } as ChangeEvent<HTMLSelectElement>);
  };

  /**
   * Назначение функции: Закрывает данные объекта «кнопка»; операция `closeAndFocusButton`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const closeAndFocusButton = () => {
    setActiveIndex(null);
    setSearch("");
    setOpen(false);

    requestAnimationFrame(() => {
      focusWithoutScroll(buttonRef.current);
    });
  };

  /**
   * Назначение функции: Обрабатывает данные объекта «результат операции `handleSelect`»; операция `handleSelect`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleSelect = (nextValue: string) => {
    emitChange(nextValue);
    closeAndFocusButton();
  };

  /**
   * Назначение функции: Обрабатывает данные объекта «результат операции `handleToggle`»; операция `handleToggle`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleToggle = () => {
    if (disabled) return;

    setOpen((current) => {
      const next = !current;

      if (next && searchable) {
        setSearch("");
      }

      if (!next) {
        setSearch("");
      }

      setActiveIndex(next ? initialActiveIndex : null);
      return next;
    });
  };

  /**
   * Назначение функции: Обрабатывает данные объекта «результат операции `handleTriggerBlur`»; операция `handleTriggerBlur`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleTriggerBlur = (event: FocusEvent<HTMLButtonElement>) => {
    const nextTarget = event.relatedTarget as Node | null;
    const movedInsideDropdown = nextTarget
      ? listRef.current?.contains(nextTarget)
      : false;

    if (!movedInsideDropdown) {
      onBlur?.(event as unknown as FocusEvent<HTMLSelectElement>);
    }
  };

  useEffect(() => {
    /**
     * Назначение функции: Обрабатывает данные объекта «результат операции `onMouseDown`»; операция `onMouseDown`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      const clickedInsideTrigger = rootRef.current?.contains(target);
      const clickedInsideDropdown = listRef.current?.contains(target);

      if (!clickedInsideTrigger && !clickedInsideDropdown) {
        setActiveIndex(null);
        setSearch("");
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

    const scrollParents = getScrollParents(buttonRef.current);
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

    const visibilityInterval = window.setInterval(() => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;

      const isOutOfViewport =
        rect.bottom < 0 ||
        rect.top > window.innerHeight ||
        rect.right < 0 ||
        rect.left > window.innerWidth;

      if (isOutOfViewport) {
        setActiveIndex(null);
        setSearch("");
        setOpen(false);
      }
    }, 150);

    return () => {
      window.cancelAnimationFrame(frame);

      scrollParents.forEach((parent) => {
        parent.removeEventListener("scroll", onScroll as EventListener);
      });

      window.removeEventListener("resize", onResize);
      window.clearInterval(visibilityInterval);
    };
  }, [open, updatePosition]);

  useLayoutEffect(() => {
    if (!open) return;

    const frame = requestAnimationFrame(() => {
      updatePosition();
    });

    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [open, searchable, search, normalizedOptions.length, updatePosition]);

  useEffect(() => {
    if (!open) return;

    if (searchable) {
      requestAnimationFrame(() => {
        focusWithoutScroll(searchInputRef.current);
      });
      return;
    }

    if (activeIndex == null) return;

    requestAnimationFrame(() => {
      focusWithoutScroll(optionRefs.current[activeIndex]);
    });
  }, [open, searchable, activeIndex, filteredOptions.length]);

  /**
   * Назначение функции: Обрабатывает данные объекта «кнопка»; операция `handleButtonKeyDown`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleButtonKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;

    if (
      event.key === "Enter" ||
      event.key === " " ||
      event.key === "ArrowDown" ||
      event.key === "ArrowUp"
    ) {
      event.preventDefault();
      setActiveIndex(initialActiveIndex);
      setOpen(true);
    }

    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      closeAndFocusButton();
    }
  };

  /**
   * Назначение функции: Обрабатывает данные объекта «ключ»; операция `handleOptionKeyDown`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleOptionKeyDown =
    (index: number, option: SelectOption) =>
    (event: KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();

        let next = index + 1;
        while (
          next < filteredOptions.length &&
          filteredOptions[next]?.disabled
        ) {
          next += 1;
        }

        if (next < filteredOptions.length) {
          setActiveIndex(next);
          focusWithoutScroll(optionRefs.current[next]);
        }
      } else if (event.key === "ArrowUp") {
        event.preventDefault();

        let prev = index - 1;
        while (prev >= 0 && filteredOptions[prev]?.disabled) {
          prev -= 1;
        }

        if (prev >= 0) {
          setActiveIndex(prev);
          focusWithoutScroll(optionRefs.current[prev]);
        }
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();

        if (!option.disabled) {
          handleSelect(option.value);
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeAndFocusButton();
      }
    };

  const dropdownAnimationClass =
    openDirection === "up"
      ? "[animation:selectOpenUp_160ms_cubic-bezier(0.22,1,0.36,1)]"
      : "[animation:selectOpenDown_160ms_cubic-bezier(0.22,1,0.36,1)]";

  const menu =
    open && !disabled && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={listRef}
            role="listbox"
            aria-label={menuAriaLabel}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                closeAndFocusButton();
              }
            }}
            className={cn(
              "overflow-hidden border border-[color:var(--select-menu-border)]",
              size ? "rounded-[8px]" : "rounded-[12px]",
              "bg-[var(--select-menu-bg)] shadow-[var(--select-menu-shadow)]",
              dropdownAnimationClass
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
            {searchable ? (
              <div className="bg-[var(--select-menu-bg)] px-2 pb-1.5 pt-2">
                <div className="flex h-9 items-center gap-2 rounded-[10px] border border-[color:var(--input-border)] bg-[var(--select-search-bg)] px-3 transition-colors focus-within:border-[color:var(--input-border-focus)] focus-within:ring-[3px] focus-within:ring-[color:var(--focus-ring)]">
                  <SearchIcon className="h-4 w-4 shrink-0 text-[color:var(--text-muted)]" />

                  <input
                    ref={searchInputRef}
                    type="text"
                    value={search}
                    onChange={(event) => {
                      const nextSearch = event.target.value;
                      const nextFiltered =
                        nextSearch.trim() === ""
                          ? normalizedOptions
                          : normalizedOptions.filter((option) => {
                              const query = nextSearch.trim().toLowerCase();

                              return (
                                option.label.toLowerCase().includes(query) ||
                                option.value.toLowerCase().includes(query)
                              );
                            });

                      setSearch(nextSearch);
                      setActiveIndex(
                        getInitialActiveIndex(nextFiltered, currentValue)
                      );
                    }}
                    placeholder={searchPlaceholder}
                    className={cn(
                      "h-full w-full border-0 bg-transparent text-sm text-[color:var(--text-primary)] outline-none",
                      "placeholder:text-[color:var(--input-placeholder)]"
                    )}
                  />
                </div>
              </div>
            ) : null}

            <div className={cn("select-scrollbar max-h-[320px] overflow-y-auto overscroll-contain", size ? "px-1 py-1" : "px-1.5 py-1.5")}>
              {filteredOptions.length === 0 ? (
                <div className="px-4 py-6">
                  <div className="flex min-h-[120px] flex-col items-center justify-center gap-2 text-center">
                    <div className="text-sm font-semibold text-[color:var(--select-empty-title)]">
                      {emptyTitle}
                    </div>

                    <div className="max-w-[26rem] text-sm leading-5 text-[color:var(--select-empty-description)]">
                      {emptyDescription}
                    </div>

                    <button
                      type="button"
                      onClick={() => {
                        setSearch("");
                        setActiveIndex(
                          getInitialActiveIndex(normalizedOptions, currentValue)
                        );
                        onEmptyAction?.();

                        requestAnimationFrame(() => {
                          focusWithoutScroll(searchInputRef.current);
                        });
                      }}
                      className={cn(
                        "mt-2 inline-flex h-8 items-center justify-center rounded-[8px] border",
                        "border-[color:var(--input-border)] bg-[var(--surface)] px-3 text-sm font-medium text-[color:var(--text-secondary)]",
                        "transition-colors hover:bg-[var(--surface-muted)]"
                      )}
                    >
                      {emptyActionLabel}
                    </button>
                  </div>
                </div>
              ) : (
                filteredOptions.map((option, index) => {
                  const isSelected = option.value === currentValue;
                  const isDisabled = Boolean(option.disabled);

                  return (
                    <button
                      key={`${option.value}-${index}`}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      disabled={isDisabled}
                      ref={(node) => {
                        optionRefs.current[index] = node;
                      }}
                      className={cn(
                        "group flex w-full items-center justify-between text-left transition-colors focus:outline-none",
                        size ? cn("gap-1.5", optionSizeClasses[size]) : "h-9 gap-3 rounded-[8px] px-3 text-sm",
                        isDisabled &&
                          "cursor-not-allowed text-[color:var(--text-muted)] opacity-60",
                        !isDisabled &&
                          "cursor-pointer text-[color:var(--select-option-fg)] hover:bg-[var(--select-option-bg-hover)] hover:text-[color:var(--select-option-fg-hover)] focus-visible:bg-[var(--select-option-bg-hover)]",
                        !isDisabled &&
                          isSelected &&
                          "bg-[var(--select-option-bg-selected)] font-medium text-[color:var(--select-option-fg-selected)]"
                      )}
                      onClick={() => {
                        if (!isDisabled) {
                          handleSelect(option.value);
                        }
                      }}
                      onKeyDown={handleOptionKeyDown(index, option)}
                    >
                      <span className="truncate">
                        {renderOption
                          ? renderOption(option, isSelected)
                          : option.label}
                      </span>

                      {isSelected ? (
                        <CheckIcon className={cn("shrink-0 text-[color:var(--select-option-fg-selected)]", size ? "h-3 w-3" : "h-4 w-4")} />
                      ) : null}
                    </button>
                  );
                })
              )}
            </div>
          </div>,
          document.body
        )
      : null;

  return (
    <div className={cn(fitContent ? "inline-block max-w-full" : "min-w-0 w-full", containerClassName)}>
      {label ? (
        <label
          htmlFor={inputId}
          className={cn(
            "mb-1.5 block text-xs font-medium leading-none",
            hasError
              ? "text-[var(--status-danger-fg)]"
              : "text-[color:var(--input-label)]"
          )}
        >
          {label}
        </label>
      ) : null}

      <div
        ref={rootRef}
        className={cn(fitContent ? "relative inline-block min-w-0 max-w-full" : "relative min-w-0 w-full max-w-full", className)}
      >
        <select
          ref={ref}
          id={inputId}
          name={name}
          value={currentValue}
          onChange={(event) => emitChange(event.target.value)}
          onBlur={onBlur}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          {...props}
        >
          {!hasPlaceholderOption ? (
            <option value="">{resolvedPlaceholder}</option>
          ) : null}

          {normalizedOptions.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>

        <button
          ref={buttonRef}
          type="button"
          id={triggerId}
          disabled={disabled}
          onClick={handleToggle}
          onKeyDown={handleButtonKeyDown}
          onBlur={handleTriggerBlur}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-label={triggerAriaLabel}
          className={cn(
            "group relative flex cursor-pointer appearance-none items-center border bg-[var(--input-background)] text-left outline-none touch-manipulation",
            fitContent ? "max-w-full" : "w-full",
            size ? triggerSizeClasses[size] : "h-[44.4px] rounded-[8px] pl-3 pr-7",
            "shadow-none transition-[background,border,box-shadow,color] duration-150 ease-[ease]",
            "disabled:cursor-not-allowed disabled:bg-[var(--input-disabled-bg)] disabled:opacity-70",
            hasError
              ? [
                  "border-[var(--status-danger-border)]",
                  "focus-visible:border-[var(--status-danger-border)]",
                  "focus-visible:ring-[3px] focus-visible:ring-[color:var(--status-danger-ring)]",
                ].join(" ")
              : [
                  "border-[color:var(--input-border)]",
                  "hover:border-[color:var(--input-border-hover)]",
                  "focus-visible:border-[color:var(--input-border-focus)]",
                  "focus-visible:ring-[3px] focus-visible:ring-[color:var(--focus-ring)]",
                ].join(" "),
            open &&
              !hasError &&
              "border-[color:var(--input-border-focus)] ring-[3px] ring-[color:var(--focus-ring)]",
            triggerClassName
          )}
        >
          <span
            className={cn(
              "block min-w-0 truncate",
              fitContent ? "w-auto whitespace-nowrap" : "w-full",
              size === "lg" ? "text-sm font-medium leading-5 tabular-nums" : size ? "text-xs font-medium leading-4 tabular-nums" : "text-base font-normal leading-[1.15]",
              hasValue
                ? (size ? "text-[color:var(--nav-item-active-text)]" : "text-[color:var(--input-text)]")
                : "text-[color:var(--input-placeholder)]"
            )}
          >
            {displayValue}
          </span>

          <span
            className={cn("pointer-events-none absolute top-1/2 flex -translate-y-1/2 items-center justify-center", size ? chevronPositionClasses[size] : "right-2.5")}
            aria-hidden="true"
          >
            <ChevronDownIcon
              className={cn(
                "h-3 w-3 transition-transform duration-150 ease-out",
                size ? "text-[color:var(--nav-item-icon)]" : "text-[color:var(--text-secondary)]",
                open && "rotate-180"
              )}
            />
          </span>
        </button>

        {menu}

        <style jsx>{`
          @keyframes selectOpenDown {
            from {
              opacity: 0;
              transform: translateY(-4px) scale(0.98);
            }

            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }

          @keyframes selectOpenUp {
            from {
              opacity: 0;
              transform: translateY(4px) scale(0.98);
            }

            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }
        `}</style>

        <style jsx global>{`
          .select-scrollbar {
            scrollbar-width: thin;
            scrollbar-color: var(--select-scrollbar-thumb) transparent;
            scrollbar-gutter: auto;
          }

          .select-scrollbar::-webkit-scrollbar {
            width: 10px;
            height: 10px;
          }

          .select-scrollbar::-webkit-scrollbar-track {
            margin: 6px 0;
            background: transparent;
          }

          .select-scrollbar::-webkit-scrollbar-thumb {
            min-height: 36px;
            border: 3px solid transparent;
            border-radius: 999px;
            background: var(--select-scrollbar-thumb) padding-box;
          }

          .select-scrollbar::-webkit-scrollbar-thumb:hover {
            background: var(--select-scrollbar-thumb-hover) padding-box;
          }

          .select-scrollbar::-webkit-scrollbar-thumb:active {
            background: var(--select-scrollbar-thumb-active) padding-box;
          }

          .select-scrollbar::-webkit-scrollbar-corner {
            background: transparent;
          }
        `}</style>
      </div>

      {error ? (
        <p className="pt-1.5 text-sm text-[color:var(--status-danger-fg,var(--danger))]">
          {error}
        </p>
      ) : helperText ? (
        <p className="pt-1.5 text-sm text-[color:var(--text-secondary)]">
          {helperText}
        </p>
      ) : null}
    </div>
  );
});

Select.displayName = "Select";

/**
 * Назначение функции: Отображает компонент `SearchIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      className={className}
      aria-hidden="true"
    >
      <circle cx="9" cy="9" r="4.5" />
      <path d="M12.5 12.5L16 16" strokeLinecap="round" />
    </svg>
  );
}

/**
 * Назначение функции: Отображает компонент `ChevronDownIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function ChevronDownIcon({ className }: { className?: string }) {
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
        d="M5.5 7.75L10 12.25L14.5 7.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Отображает компонент `CheckIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function CheckIcon({ className }: { className?: string }) {
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
        d="M5 10.5L8.25 13.75L15 7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
