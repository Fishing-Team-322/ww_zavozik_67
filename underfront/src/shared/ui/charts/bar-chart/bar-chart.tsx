"use client";

import * as React from "react";
import {
  Bar,
  BarChart as RechartsBarChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@/src/shared/lib/cn";
import {
  resolveChartState,
  type ChartDataPoint,
  type ChartSeriesConfig,
  type ChartStateProps,
} from "@/src/shared/ui/charts/shared";

type BarChartProps = ChartStateProps & {
  data: ChartDataPoint[];
  xKey: string;
  series: ChartSeriesConfig[];
  colorKey?: string;
  title?: string;
  metricValue?: string | number;
  metricLabel?: string;
  metricPrefix?: string;
  defaultActiveIndex?: number;
  className?: string;
};

/**
 * Назначение функции: Отображает компонент `BarChart` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function BarChart({
  data,
  xKey,
  series,
  colorKey,
  title = "Bar chart",
  metricValue,
  metricLabel = "Monthly avg",
  metricPrefix = "",
  defaultActiveIndex,
  className,
  ...state
}: BarChartProps) {
  const chartState = resolveChartState(data, state);
  const primarySeries = series[0];

  const safeDefaultIndex = React.useMemo(() => {
    if (!data.length) return 0;
    if (typeof defaultActiveIndex === "number") {
      return Math.max(0, Math.min(defaultActiveIndex, data.length - 1));
    }
    return Math.min(Math.floor(data.length / 2), data.length - 1);
  }, [data.length, defaultActiveIndex]);

  const [selectedIndex, setSelectedIndex] = React.useState(safeDefaultIndex);
  const [hoveredIndex, setHoveredIndex] = React.useState<number | null>(null);

  React.useEffect(() => {
    setSelectedIndex(safeDefaultIndex);
  }, [safeDefaultIndex]);

  const selectedEntry = data[selectedIndex];
  const selectedLabel =
    selectedEntry != null
      ? String(selectedEntry[xKey] ?? metricLabel)
      : metricLabel;

  const selectedNumericValue = React.useMemo(() => {
    if (selectedEntry && primarySeries) {
      return getNumericValue(selectedEntry, primarySeries.key);
    }

    if (typeof metricValue === "number") {
      return metricValue;
    }

    return 0;
  }, [metricValue, primarySeries, selectedEntry]);

  const animatedMetricValue = useAnimatedNumber(selectedNumericValue, 240);

  const resolvedMetric = React.useMemo(() => {
    if (selectedEntry && primarySeries) {
      return `${metricPrefix}${formatMetric(animatedMetricValue, 0)}`;
    }

    if (typeof metricValue === "string") return metricValue;
    if (typeof metricValue === "number") {
      return `${metricPrefix}${formatMetric(animatedMetricValue, 0)}`;
    }

    return `${metricPrefix}0`;
  }, [
    animatedMetricValue,
    metricPrefix,
    metricValue,
    primarySeries,
    selectedEntry,
  ]);

  if (chartState.loading) {
    return (
      <BlueChartShell className={className}>
        <div className="h-full w-full animate-pulse rounded-[24px] bg-white/10" />
      </BlueChartShell>
    );
  }

  if (chartState.isEmpty) {
    return (
      <BlueChartShell className={className}>
        <div className="flex h-full min-h-[360px] items-center justify-center text-center text-white/82">
          <div>
            <div className="text-lg font-semibold">
              {chartState.emptyTitle ?? "Нет данных"}
            </div>
            <div className="mt-1 text-sm text-white/64">
              {chartState.emptyDescription ??
                "Недостаточно данных для построения графика"}
            </div>
          </div>
        </div>
      </BlueChartShell>
    );
  }

  return (
    <BlueChartShell className={className}>
      <div className="relative z-[1] flex h-full min-h-[360px] flex-col">
        <div className="mb-5">
          <div className="mb-4 flex items-center gap-2 text-[color:var(--brand-foreground)]">
            <BarsIcon className="h-5 w-5 opacity-95" />
            <span className="text-[15px] font-semibold tracking-[0.01em]">
              {title}
            </span>
          </div>

          <div className="text-[44px] font-semibold leading-none tracking-[-0.03em] text-[color:var(--brand-foreground)]">
            {resolvedMetric}
          </div>

          <div className="mt-2 text-[15px] text-white/62 transition-opacity duration-200">
            {selectedLabel}
          </div>
        </div>

        <div className="min-h-0 flex-1">
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={260}
            minHeight={220}
          >
            <RechartsBarChart
              data={data}
              barCategoryGap="22%"
              margin={{ top: 8, right: 4, bottom: 6, left: 4 }}
            >
              <XAxis
                dataKey={xKey}
                axisLine={false}
                tickLine={false}
                interval={0}
                height={42}
                tickMargin={10}
                tick={
                  <InteractiveBarTick
                    selectedIndex={selectedIndex}
                    hoveredIndex={hoveredIndex}
                    onSelect={setSelectedIndex}
                    onHover={setHoveredIndex}
                  />
                }
              />

              <YAxis hide domain={[0, "dataMax + 10"]} />

              <Bar
                dataKey={primarySeries?.key}
                radius={[999, 999, 999, 999]}
                maxBarSize={18}
                isAnimationActive
                animationDuration={380}
                shape={(shapeProps: unknown) => (
                  <InteractiveRoundedBar
                    {...(shapeProps as Parameters<typeof InteractiveRoundedBar>[0])}
                    colorKey={colorKey}
                    selectedIndex={selectedIndex}
                    hoveredIndex={hoveredIndex}
                    onSelect={setSelectedIndex}
                    onHover={setHoveredIndex}
                  />
                )}
              />
            </RechartsBarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </BlueChartShell>
  );
}

/**
 * Назначение функции: Отображает компонент `BlueChartShell` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function BlueChartShell({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative h-full overflow-hidden rounded-[var(--radius-lg)] p-6",
        className
      )}
      style={{
        background:
          "linear-gradient(180deg, color-mix(in srgb, var(--brand) 92%, white 10%) 0%, var(--brand) 100%)",
      }}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 90% at 0% 0%, rgba(255,255,255,0.18) 0%, rgba(255,255,255,0) 46%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0) 34%, rgba(0,0,0,0.08) 100%)",
        }}
      />
      {children}
    </div>
  );
}

/**
 * Назначение функции: Отображает компонент `InteractiveRoundedBar` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function InteractiveRoundedBar({
  x = 0,
  y = 0,
  width = 0,
  height = 0,
  index = 0,
  payload,
  colorKey,
  selectedIndex,
  hoveredIndex,
  onSelect,
  onHover,
}: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  index?: number;
  payload?: ChartDataPoint;
  colorKey?: string;
  selectedIndex: number;
  hoveredIndex: number | null;
  onSelect: (index: number) => void;
  onHover: (index: number | null) => void;
}) {
  const isSelected = index === selectedIndex;
  const isHovered = index === hoveredIndex;

  const customColor = colorKey ? String(payload?.[colorKey] ?? "") : "";
  const fill =
    customColor ||
    (isSelected
      ? "rgba(255,255,255,0.98)"
      : isHovered
        ? "rgba(255,255,255,0.62)"
        : "rgba(255,255,255,0.30)");

  const visualWidth = Math.min(16, width);
  const hitWidth = Math.max(38, visualWidth + 24);

  const visualX = x + (width - visualWidth) / 2;
  const hitX = x + (width - hitWidth) / 2;

  return (
    <g>
      <rect
        x={hitX}
        y={Math.max(0, y - 10)}
        width={hitWidth}
        height={height + 20}
        rx={Math.min(hitWidth / 2, 18)}
        fill="transparent"
        style={{ cursor: "pointer" }}
        onMouseEnter={() => onHover(index)}
        onMouseLeave={() => onHover(null)}
        onClick={() => onSelect(index)}
      />
      <rect
        x={visualX}
        y={y}
        width={visualWidth}
        height={height}
        rx={visualWidth / 2}
        fill={fill}
        style={{
          transition:
            "fill 220ms ease, opacity 220ms ease, transform 220ms ease, y 220ms ease, height 220ms ease",
          cursor: "pointer",
        }}
        onMouseEnter={() => onHover(index)}
        onMouseLeave={() => onHover(null)}
        onClick={() => onSelect(index)}
      />
    </g>
  );
}

/**
 * Назначение функции: Отображает компонент `InteractiveBarTick` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function InteractiveBarTick({
  x = 0,
  y = 0,
  payload,
  index,
  selectedIndex,
  hoveredIndex,
  onSelect,
  onHover,
}: {
  x?: number;
  y?: number;
  payload?: { value?: string | number };
  index?: number;
  selectedIndex: number;
  hoveredIndex: number | null;
  onSelect: (index: number) => void;
  onHover: (index: number | null) => void;
}) {
  const safeIndex = typeof index === "number" ? index : 0;
  const label = String(payload?.value ?? "");
  const isSelected = safeIndex === selectedIndex;
  const isHovered = safeIndex === hoveredIndex;
  const pillWidth = Math.max(38, label.length * 8 + 18);
  const hitWidth = Math.max(54, pillWidth + 10);

  return (
    <g
      transform={`translate(${x},${y + 12})`}
      onMouseEnter={() => onHover(safeIndex)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onSelect(safeIndex)}
      style={{ cursor: "pointer" }}
    >
      <rect
        x={-hitWidth / 2}
        y={-18}
        width={hitWidth}
        height={34}
        rx={17}
        fill="transparent"
      />

      <rect
        x={-pillWidth / 2}
        y={-14}
        width={pillWidth}
        height={26}
        rx={13}
        fill={isSelected ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0)"}
        style={{
          transition: "fill 220ms ease, opacity 220ms ease",
        }}
      />

      <text
        x={0}
        y={3}
        textAnchor="middle"
        fontSize="12"
        fontWeight={isSelected || isHovered ? 600 : 500}
        fill={
          isSelected
            ? "var(--brand-active)"
            : isHovered
              ? "rgba(255,255,255,1)"
              : "rgba(255,255,255,0.84)"
        }
        style={{
          transition: "fill 220ms ease, opacity 220ms ease",
          pointerEvents: "none",
        }}
      >
        {label}
      </text>
    </g>
  );
}

/**
 * Назначение функции: Отображает компонент `BarsIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function BarsIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M4 20h16"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.95"
      />
      <path
        d="M7 20V12"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="M12 20V8"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="M17 20V5"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Возвращает данные объекта «значение»; операция `getNumericValue`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function getNumericValue(entry: ChartDataPoint, key: string) {
  const raw = entry[key];
  return typeof raw === "number" ? raw : Number(raw ?? 0);
}

/**
 * Назначение функции: Форматирует данные объекта «метрика»; операция `formatMetric`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function formatMetric(value: number, maximumFractionDigits = 0) {
  const normalized = maximumFractionDigits === 0 ? Math.round(value) : value;

  // The cabinet is Russian-language: an en-US grouping renders 141,800,000
  // where the rest of the screen shows 141 800 000.
  return new Intl.NumberFormat("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(normalized);
}

/**
 * Назначение функции: Предоставляет React-хук `useAnimatedNumber` для данных, состояния или действий: число.
 * Зачем используется: Позволяет компонентам использовать этот сценарий со стабильным порядком вызова хуков.
 */
function useAnimatedNumber(target: number, duration = 240) {
  const [value, setValue] = React.useState(target);
  const previousRef = React.useRef(target);

  React.useEffect(() => {
    const from = previousRef.current;
    const to = target;

    if (from === to) return;

    let frame = 0;
    const startedAt = performance.now();

    /**
     * Назначение функции: Выполняет операцию `easeOutCubic` для объекта «число». Возвращает результат выражения: `1 - Math.pow(1 - t, 3)`.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

    /**
     * Назначение функции: Выполняет операцию `tick` для объекта «число». Выполняет вызовы: `Math.min`, `easeOutCubic`, `setValue`; значение не возвращает.
     * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
     */
    const tick = (now: number) => {
      const elapsed = now - startedAt;
      const progress = Math.min(elapsed / duration, 1);
      const eased = easeOutCubic(progress);
      const next = from + (to - from) * eased;

      setValue(next);

      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        previousRef.current = to;
        setValue(to);
      }
    };

    frame = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(frame);
  }, [target, duration]);

  return value;
}
