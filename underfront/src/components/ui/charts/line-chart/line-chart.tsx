"use client";

import { useId } from "react";
import {
  Area,
  AreaChart as RechartsAreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { chartPalette } from "@/src/lib/charts";
import {
  ChartEmptyState,
  ChartLegend,
  resolveChartState,
  type ChartDataPoint,
  type ChartSeriesConfig,
  type ChartStateProps,
} from "@/src/components/ui/charts/shared";

type LineChartProps = ChartStateProps & {
  data: ChartDataPoint[];
  xKey: string;
  series: ChartSeriesConfig[];
};

const numberFormatter = new Intl.NumberFormat("ru-RU");

/**
 * Назначение функции: Отображает компонент `LineChart` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function LineChart({ data, xKey, series, ...state }: LineChartProps) {
  const chartState = resolveChartState(data, state);
  const uid = useId().replace(/:/g, "");
  const hasLegend = series.length > 1;

  if (chartState.loading) {
    return (
      <div className="h-full min-h-[320px] w-full min-w-0">
        {chartState.loadingFallback ?? (
          <div className="h-full w-full animate-pulse rounded-xl bg-[color:var(--surface-muted)]" />
        )}
      </div>
    );
  }

  if (chartState.isEmpty) {
    return (
      <div className="flex h-full min-h-[320px] w-full min-w-0 items-center justify-center">
        <ChartEmptyState
          title={chartState.emptyTitle}
          description={chartState.emptyDescription}
        />
      </div>
    );
  }

  return (
    <div className="h-full min-h-[320px] w-full min-w-0">
      <ResponsiveContainer
        width="100%"
        height="100%"
        minWidth={280}
        minHeight={320}
      >
        <RechartsAreaChart
          data={data}
          margin={{
            top: hasLegend ? 42 : 18,
            right: 18,
            bottom: 10,
            left: 6,
          }}
        >
          <defs>
            {series.map((item, index) => {
              const gradientId = `area-fill-${uid}-${item.key}`;
              const topOpacity = index === 0 ? 0.24 : 0.18;

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
                    offset="42%"
                    stopColor={item.color}
                    stopOpacity={0.09}
                  />
                  <stop
                    offset="100%"
                    stopColor={item.color}
                    stopOpacity={0.015}
                  />
                </linearGradient>
              );
            })}
          </defs>

          <CartesianGrid
            vertical
            syncWithTicks
            strokeDasharray="2 6"
            stroke="rgba(143, 158, 180, 0.12)"
          />

          <XAxis
            dataKey={xKey}
            tick={{ fontSize: 12, fill: "var(--chart-axis)" }}
            tickLine={false}
            axisLine={false}
            tickMargin={12}
            minTickGap={18}
            padding={{ left: 12, right: 12 }}
          />

          <YAxis
            tick={{ fontSize: 12, fill: "var(--chart-axis)" }}
            tickLine={false}
            axisLine={false}
            tickMargin={10}
            width={42}
          />

          <Tooltip
            cursor={<OverlayChartCursor />}
            content={<OverlayChartTooltip />}
          />

          {hasLegend ? (
            <Legend
              verticalAlign="top"
              align="left"
              height={28}
              wrapperStyle={{
                top: 0,
                left: 8,
                right: 8,
                fontSize: 12,
              }}
              content={<ChartLegend />}
            />
          ) : null}

          {series.map((item) => {
            const gradientId = `area-fill-${uid}-${item.key}`;

            return (
              <Area
                key={item.key}
                type="natural"
                dataKey={item.key}
                name={item.name}
                stroke={item.color}
                fill={`url(#${gradientId})`}
                strokeWidth={2.5}
                strokeOpacity={0.95}
                fillOpacity={1}
                dot={false}
                activeDot={{
                  r: 5,
                  fill: item.color,
                  stroke: "#dffef6",
                  strokeWidth: 2,
                }}
                isAnimationActive
                animationDuration={550}
              />
            );
          })}
        </RechartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * Назначение функции: Отображает компонент `OverlayChartTooltip` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function OverlayChartTooltip({
  active,
  payload,
  label,
}: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;

  const items = [...payload]
    .filter((entry) => typeof entry.value === "number")
    .sort((a, b) => Number(a.value ?? 0) - Number(b.value ?? 0));

  return (
    <div className="min-w-[164px] rounded-[16px] border border-white/10 bg-[#0b1016]/95 px-4 py-3 shadow-[0_18px_50px_rgba(0,0,0,0.45)] backdrop-blur-md">
      <div className="mb-2 text-xs font-medium text-white/70">{label}</div>

      <div className="space-y-1.5">
        {items.map((entry) => (
          <div key={String(entry.dataKey)} className="flex items-center gap-2">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: entry.color ?? chartPalette.cyan }}
            />
            <span className="text-[13px] text-white/78">{entry.name}:</span>
            <span
              className="ml-auto text-[13px] font-semibold"
              style={{ color: entry.color ?? chartPalette.cyan }}
            >
              {numberFormatter.format(Number(entry.value ?? 0))}
            </span>
          </div>
        ))}
      </div>

    </div>
  );
}

/**
 * Назначение функции: Отображает компонент `OverlayChartCursor` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function OverlayChartCursor(props: {
  points?: Array<{ x: number; y: number }>;
  top?: number;
  height?: number;
}) {
  const x = props.points?.[0]?.x;
  const top = props.top ?? 0;
  const height = props.height ?? 0;

  if (x == null || height <= 0) return null;

  const lineTop = top + 2;
  const lineBottom = top + height - 10;
  const triangleApexY = top + height - 8;
  const triangleBaseY = top + height - 2;

  return (
    <g>
      <line
        x1={x}
        y1={lineTop}
        x2={x}
        y2={lineBottom}
        stroke="rgba(255,255,255,0.38)"
        strokeWidth={1}
      />
      <polygon
        points={`${x},${triangleApexY} ${x - 5},${triangleBaseY} ${x + 5},${triangleBaseY}`}
        fill="#0b1016"
        stroke="rgba(255,255,255,0.16)"
        strokeWidth={1}
      />
    </g>
  );
}
