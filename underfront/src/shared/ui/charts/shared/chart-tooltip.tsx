import { type TooltipProps } from "recharts";
import {
  type NameType,
  type ValueType,
} from "recharts/types/component/DefaultTooltipContent";

type ChartTooltipProps = TooltipProps<ValueType, NameType> & {
  labelPrefix?: string;
  valueFormatter?: (value: number, key?: string) => string;
};

/**
 * Назначение функции: Отображает компонент `ChartTooltip` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  labelPrefix,
  valueFormatter,
}: ChartTooltipProps) {
  if (!active || !payload?.length) {
    return null;
  }

  return (
    <div className="min-w-44 rounded-[var(--radius-md)] border border-[color:var(--chart-panel-border)] bg-[color:var(--chart-tooltip-bg)] p-3 shadow-[var(--shadow-md)]">
      {label ? (
        <p className="mb-2 text-xs font-semibold text-[color:var(--chart-title)]">
          {labelPrefix ? `${labelPrefix}: ` : ""}
          {label}
        </p>
      ) : null}
      <div className="space-y-1.5">
        {payload.map((entry, index) => {
          const numericValue =
            typeof entry.value === "number"
              ? entry.value
              : Number(entry.value ?? 0);
          return (
            <div
              key={`${entry.name}-${index}`}
              className="flex items-center justify-between gap-3 text-xs"
            >
              <span className="text-[color:var(--chart-subtitle)]">{entry.name}</span>
              <span className="font-semibold text-[color:var(--chart-title)]">
                {valueFormatter
                  ? valueFormatter(numericValue, String(entry.dataKey))
                  : numericValue.toLocaleString("ru-RU")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
