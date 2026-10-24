"use client";

import { ReactNode, useId, useState } from "react";
import { cn } from "@/src/shared/lib/cn";

export interface TabItem {
  key: string;
  label: ReactNode;
  content: ReactNode;
  disabled?: boolean;
}

interface TabsProps {
  tabs: TabItem[];
  ariaLabel?: string;
  defaultValue?: string;
  className?: string;
  listClassName?: string;
  triggerClassName?: string;
  contentClassName?: string;
  size?: "sm" | "md" | "lg";
  value?: string;
  onValueChange?: (value: string) => void;
  showContent?: boolean;
}

const tabSizeClasses: Record<NonNullable<TabsProps["size"]>, string> = {
  sm: "h-5 px-1.5",
  md: "h-6 px-2",
  lg: "h-8 px-3",
};

/** Назначение функции: Переключает доступные панели с клавиатуры и мышью; скрытая или отключённая вкладка никогда не монтирует свой контент.
 * Зачем используется: Сохраняет доступность переключения панелей и не запускает содержимое отключённых вкладок.
 */
export function Tabs({
  tabs,
  ariaLabel,
  defaultValue,
  className,
  listClassName,
  triggerClassName,
  contentClassName,
  size = "md",
  value,
  onValueChange,
  showContent = true,
}: TabsProps) {
  const layoutId = useId();

  const [internalValue, setInternalValue] = useState(defaultValue);
  // После смены организации/прав устаревший выбор не должен открывать запрещённую панель.
  const current =
    tabs.find((tab) => tab.key === (value ?? internalValue) && !tab.disabled) ??
    tabs.find((tab) => !tab.disabled);
  const activeTab = current?.key;

  /** Назначение функции: Выбирает только разрешённую вкладку и уведомляет владельца управляемого компонента.
   * Зачем используется: Согласует внутреннее состояние вкладок с управляемым значением владельца и исключает выбор отключённой панели.
   */
  function selectTab(key: string) {
    if (!tabs.some((tab) => tab.key === key && !tab.disabled)) return;
    setInternalValue(key);
    onValueChange?.(key);
  }

  return (
    <div className={cn("min-w-0 space-y-5", className)}>
      <div
        role="tablist"
        aria-label={ariaLabel}
        aria-orientation="horizontal"
        className={cn(
          [
            "relative isolate",
            "inline-flex max-w-full shrink-0 flex-wrap items-center gap-0.5 p-0.5",
            "overflow-visible",
            "rounded-[6px]",
            "bg-[var(--tabs-bg)] text-[color:var(--tabs-fg)]",
            "font-normal tabular-nums",
          ].join(" "),
          listClassName
        )}
      >
        {tabs.map((tab, index) => {
          const isActive = activeTab === tab.key;

          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              id={`${layoutId}-tab-${index}`}
              aria-controls={
                showContent ? `${layoutId}-panel-${index}` : undefined
              }
              tabIndex={isActive ? 0 : -1}
              aria-selected={isActive}
              aria-disabled={tab.disabled}
              disabled={tab.disabled}
              onClick={() => selectTab(tab.key)}
              onKeyDown={(event) => {
                if (
                  !["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                    event.key
                  )
                )
                  return;
                event.preventDefault();
                const enabled = tabs.filter((item) => !item.disabled);
                const position = enabled.findIndex(
                  (item) => item.key === tab.key
                );
                const next =
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? enabled.length - 1
                      : (position +
                          (event.key === "ArrowRight" ? 1 : -1) +
                          enabled.length) %
                        enabled.length;
                const target = enabled[next];
                if (!target) return;
                selectTab(target.key);
                const buttons =
                  event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                    '[role="tab"]'
                  );
                buttons?.[
                  tabs.findIndex((item) => item.key === target.key)
                ]?.focus({ preventScroll: true });
              }}
              className={cn(
                [
                  "inline-flex",
                  "cursor-pointer",
                  "items-center",
                  "justify-center",
                  "gap-1",
                  "whitespace-nowrap",
                  "rounded-[4px]",
                  "font-medium text-sm leading-4",
                  "transition-[background-color,color,box-shadow]",
                  "duration-200",
                  "ease-out",

                  "focus-visible:outline-none",
                  "focus-visible:ring-2",
                  "focus-visible:ring-[color:var(--focus-ring-strong)]",
                  "focus-visible:ring-offset-2",
                  "focus-visible:ring-offset-[color:var(--focus-ring-offset)]",

                  "disabled:pointer-events-none",
                  "disabled:opacity-55",
                ].join(" "),

                tabSizeClasses[size],

                isActive
                  ? [
                      "bg-[var(--tabs-active-bg)]",
                      "shadow-[var(--tabs-active-shadow)]",
                      "text-[var(--tabs-active-fg)]",
                    ].join(" ")
                  : [
                      "bg-transparent",
                      "text-[var(--tabs-fg)]",

                      "hover:bg-[var(--tabs-hover-bg)]",
                      "hover:text-[var(--tabs-active-fg)]",

                      "active:bg-[var(--tabs-hover-bg)]",
                    ].join(" "),

                triggerClassName
              )}
            >
              <span className="inline-flex h-4 min-w-full items-center justify-center gap-1 text-center">
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>

      {showContent && current ? (
        <div
          key={activeTab}
          id={`${layoutId}-panel-${tabs.indexOf(current)}`}
          role="tabpanel"
          aria-labelledby={`${layoutId}-tab-${tabs.indexOf(current)}`}
          className={cn("min-w-0", contentClassName)}
        >
          {current.content}
        </div>
      ) : null}
    </div>
  );
}
