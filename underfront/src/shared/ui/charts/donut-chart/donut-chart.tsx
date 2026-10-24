"use client";

import * as React from "react";
import { Cell, Pie, PieChart as RechartsPieChart } from "recharts";
import { cn } from "@/src/shared/lib/cn";
import {
  ChartEmptyState,
  resolveChartState,
  type ChartStateProps,
} from "@/src/shared/ui/charts/shared";

type DonutChartData = {
  name: string;
  value: number;
};

type DonutChartProps = ChartStateProps & {
  data: DonutChartData[];
  colors?: string[];
  title?: string;
  metricValue?: string | number;
  metricLabel?: string;
  className?: string;
  chartSize?: number;
  innerRadius?: number;
  outerRadius?: number;
};

const DEFAULT_DONUT_COLORS = [
  "rgba(232, 229, 255, 0.74)",
  "rgba(147, 129, 255, 0.92)",
  "rgba(118, 102, 255, 0.88)",
  "rgba(255, 255, 255, 0.98)",
];

/**
 * Назначение функции: Отображает компонент `DonutChart` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function DonutChart({
  data,
  colors = DEFAULT_DONUT_COLORS,
  title = "Donut chart",
  metricValue,
  metricLabel = "Avg daily steps",
  className,
  chartSize = 150,
  innerRadius = 8,
  outerRadius = 58,
  ...state
}: DonutChartProps) {
  const chartState = resolveChartState(data, state);
  const palette = colors.length ? colors : DEFAULT_DONUT_COLORS;

  const total = React.useMemo(
    () => data.reduce((sum, item) => sum + Number(item.value ?? 0), 0),
    [data]
  );

  const legendItems = React.useMemo(
    () =>
      data.map((item, index) => ({
        ...item,
        color: palette[index % palette.length],
        percent: total > 0 ? (Number(item.value ?? 0) / total) * 100 : 0,
      })),
    [data, palette, total]
  );

  const resolvedMetricValue =
    typeof metricValue === "string"
      ? metricValue
      : formatMetric(
          typeof metricValue === "number" ? metricValue : total,
          hasFraction(typeof metricValue === "number" ? metricValue : total)
            ? 2
            : 0
        );

  if (chartState.loading) {
    return (
      <DonutChartShell className={className}>
        <div className="h-full min-h-[414px] w-full animate-pulse rounded-[24px] bg-white/10" />
      </DonutChartShell>
    );
  }

  if (chartState.isEmpty) {
    return (
      <DonutChartShell className={className}>
        <div className="flex h-full min-h-[414px] items-center justify-center">
          <ChartEmptyState
            title={chartState.emptyTitle}
            description={chartState.emptyDescription}
          />
        </div>
      </DonutChartShell>
    );
  }

  return (
    <DonutChartShell className={className}>
      <div className="relative z-[1] flex h-full min-h-[414px] flex-col">
        <div className="mb-4">
          <div className="mb-4 flex items-center gap-2 text-[var(--primary-foreground,#ffffff)]">
            <DonutIcon className="h-5 w-5 opacity-95" />
            <span className="text-[15px] font-semibold tracking-[0.01em]">
              {title}
            </span>
          </div>

          <div className="text-[44px] font-semibold leading-none tracking-[-0.03em] text-[var(--primary-foreground,#ffffff)]">
            {resolvedMetricValue}
          </div>

          <div className="mt-2 text-[15px] text-white/70">{metricLabel}</div>
        </div>

        <div className="mx-auto mt-1 flex shrink-0 items-center justify-center">
          <RechartsPieChart width={chartSize} height={chartSize}>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              startAngle={90}
              endAngle={-270}
              innerRadius={innerRadius}
              outerRadius={outerRadius}
              paddingAngle={3}
              cornerRadius={10}
              stroke="none"
              isAnimationActive={false}
            >
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={palette[index % palette.length]} />
              ))}
            </Pie>

            <Pie
              data={[{ name: "center", value: 1 }]}
              dataKey="value"
              cx="50%"
              cy="50%"
              innerRadius={0}
              outerRadius={9}
              stroke="none"
              isAnimationActive={false}
            >
              <Cell fill="rgba(34, 197, 94, 0.96)" />
            </Pie>
          </RechartsPieChart>
        </div>

        <div className="mt-5 grid gap-2">
          {legendItems.map((item) => (
            <div key={item.name} className="flex items-center justify-between">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  className="h-[6px] w-[6px] shrink-0 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                <span className="truncate text-[13px] font-medium text-white/88">
                  {item.name}
                </span>
              </div>

              <span className="shrink-0 pl-3 text-[13px] font-semibold tabular-nums text-white/95">
                {formatPercent(item.percent)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </DonutChartShell>
  );
}

/**
 * Назначение функции: Отображает компонент `DonutChartShell` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function DonutChartShell({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative h-full overflow-hidden rounded-[var(--radius-lg)] p-6 shadow-[var(--shadow-md)]",
        className
      )}
      style={{
        background:
          "linear-gradient(180deg, var(--primary,#22c55e) 0%, #15803d 100%)",
      }}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 90% at 0% 0%, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0) 46%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0) 34%, rgba(0,0,0,0.08) 100%)",
        }}
      />
      {children}
    </div>
  );
}

/**
 * Назначение функции: Отображает компонент `DonutIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function DonutIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M12 3.5a8.5 8.5 0 1 1-8.5 8.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M12 3.5v8.5H3.5"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Форматирует данные объекта «метрика»; операция `formatMetric`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function formatMetric(value: number, maximumFractionDigits = 2) {
  // The cabinet is Russian-language: an en-US grouping renders 141,800,000
  // where the rest of the screen shows 141 800 000.
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: maximumFractionDigits > 0 ? 2 : 0,
    maximumFractionDigits,
  }).format(value);
}

/**
 * Назначение функции: Форматирует данные объекта «формат представления»; операция `formatPercent`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

/**
 * Назначение функции: Возвращает признак допустимости или наличия: результат операции `hasFraction`.
 * Зачем используется: Выносит условие в одну именованную проверку, используемую вызывающим кодом.
 */
function hasFraction(value: number) {
  return Math.abs(value % 1) > 0.001;
}
