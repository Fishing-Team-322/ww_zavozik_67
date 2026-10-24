import { type LegendProps } from "recharts";

/**
 * Назначение функции: Отображает компонент `ChartLegend` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function ChartLegend({ payload }: LegendProps) {
  if (!payload?.length) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
      {payload.map((entry) => (
        <div
          key={`${entry.value}-${entry.dataKey}`}
          className="inline-flex items-center gap-2 text-xs text-[color:var(--chart-subtitle)]"
        >
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{
              backgroundColor: entry.color ?? "var(--chart-series-slate)",
            }}
          />
          <span>{entry.value}</span>
        </div>
      ))}
    </div>
  );
}
