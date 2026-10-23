"use client";

import { useId, useMemo } from "react";
import {
  Area,
  AreaChart as RechartsAreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { chartPalette } from "@/src/lib/charts";
import {
  ChartEmptyState,
  resolveChartState,
  type ChartDataPoint,
  type ChartSeriesConfig,
  type ChartStateProps,
} from "@/src/components/ui/charts/shared";

type AreaChartProps = ChartStateProps & {
  data: ChartDataPoint[];
  xKey: string;
  series: ChartSeriesConfig[];
  height?: number;
};

type NormalizedPoint = Record<string, string | number | null | undefined>;

const numberFormatter = new Intl.NumberFormat("ru-RU");

/**
 * Назначение функции: Отображает компонент `AreaChart` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function AreaChart({
  data,
  xKey,
  series,
  height = 288,
  ...state
}: AreaChartProps) {
  const chartState = resolveChartState(data, state);
  const uid = useId().replace(/:/g, "");
  const chartData = useMemo<NormalizedPoint[]>(() => {
    return data.map((point) => {
      const normalized: NormalizedPoint = {
        ...point,
        [xKey]: String(point[xKey] ?? ""),
      };

      for (const item of series) {
        const rawValue = point[item.key];
        normalized[item.key] =
          typeof rawValue === "number" ? rawValue : Number(rawValue ?? 0);
      }

      return normalized;
    });
  }, [data, series, xKey]);

  const yDomain = useMemo<[number, number]>(() => {
    const values = chartData
      .flatMap((point) =>
        series.map((item) => {
          const value = point[item.key];
          return typeof value === "number" ? value : Number(value ?? 0);
        })
      )
      .filter((value) => Number.isFinite(value));

    if (!values.length) return [0, 100];

    const min = Math.min(...values);
    const max = Math.max(...values);

    if (min === max) return [min - 1, max + 1];

    const padding = (max - min) * 0.18;
    return [min - padding, max + padding];
  }, [chartData, series]);

  if (chartState.loading) {
    return (
      <div className="w-full min-w-0" style={{ height }}>
        {chartState.loadingFallback ?? (
          <div className="h-full w-full animate-pulse rounded-xl bg-[color:var(--surface-muted)]" />
        )}
      </div>
    );
  }

  if (chartState.isEmpty) {
    return (
      <div
        className="flex w-full min-w-0 items-center justify-center"
        style={{ height }}
      >
        <ChartEmptyState
          title={chartState.emptyTitle}
          description={chartState.emptyDescription}
        />
      </div>
    );
  }

  return (
    <div className="w-full min-w-0" style={{ height }}>
      <ResponsiveContainer
        width="100%"
        height="100%"
        minWidth={260}
        minHeight={height}
      >
        <RechartsAreaChart
          data={chartData}
          margin={{ top: 8, right: 16, bottom: 10, left: 16 }}
        >
          <defs>
            {series.map((item, index) => {
              const gradientId = `area-chart-${uid}-${item.key}`;
              const topOpacity = index === 0 ? 0.2 : 0.12;

              return (
                <linearGradient
                  key={gradientId}
                  id={gradientId}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor={item.color}
                    stopOpacity={topOpacity}
                  />
                  <stop
                    offset="58%"
                    stopColor={item.color}
                    stopOpacity={0.07}
                  />
                  <stop offset="100%" stopColor={item.color} stopOpacity={0} />
                </linearGradient>
              );
            })}
          </defs>

          <CartesianGrid horizontal={false} vertical={false} />

          <XAxis
            dataKey={xKey}
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 12, fill: "var(--chart-axis)" }}
            tickMargin={12}
            minTickGap={18}
            padding={{ left: 8, right: 8 }}
          />

          <YAxis hide domain={yDomain} />

          <Tooltip
            cursor={{
              stroke: "rgba(255,255,255,0.14)",
              strokeWidth: 1,
            }}
            content={<AreaChartTooltip series={series} />}
          />

          {series.map((item, index) => {
            const gradientId = `area-chart-${uid}-${item.key}`;

            return (
              <Area
                key={item.key}
                type="linear"
                dataKey={item.key}
                name={item.name}
                stroke={item.color}
                fill={index === 0 ? `url(#${gradientId})` : "transparent"}
                strokeWidth={2.2}
                strokeOpacity={0.95}
                fillOpacity={1}
                dot={false}
                activeDot={{
                  r: 4,
                  fill: item.color,
                  stroke: "#dffef6",
                  strokeWidth: 2,
                }}
                isAnimationActive
                animationDuration={480}
              />
            );
          })}
        </RechartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Назначение функции: Отображает компонент `AreaChartTooltip` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function AreaChartTooltip({
  active,
  payload,
  label,
  series,
}: TooltipProps<number, string> & { series: ChartSeriesConfig[] }) {
  if (!active || !payload?.length) return null;

  return (
    <div className="min-w-[164px] rounded-[10px] bg-[color:var(--chart-tooltip-bg)] px-3 py-2 shadow-[0_10px_30px_rgba(0,0,0,0.24)]">
      <div className="mb-2 text-sm font-semibold text-[color:var(--chart-title)]">
        {label}
      </div>

      <div className="space-y-1.5">
        {payload.map((entry) => {
          const config = series.find((item) => item.key === entry.dataKey);
          const value = Number(entry.value ?? 0);

          return (
            <div
              key={String(entry.dataKey)}
              className="flex items-center gap-2 text-xs"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{
                  backgroundColor:
                    config?.color ?? entry.color ?? chartPalette.cyan,
                }}
              />
              <span className="text-[color:var(--chart-subtitle)]">
                {config?.name ?? entry.name}:
              </span>
              <span className="ml-auto font-semibold text-[color:var(--chart-title)]">
                {config?.formatter
                  ? config.formatter(value)
                  : numberFormatter.format(value)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
