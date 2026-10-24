import { type ReactNode } from "react";
import { Card } from "@/src/shared/ui/card";
import { cn } from "@/src/shared/lib/cn";

type ChartCardProps = {
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  headerSlot?: ReactNode;
};

/**
 * Назначение функции: Отображает компонент `ChartCard` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function ChartCard({
  title,
  description,
  children,
  className,
  contentClassName,
  headerSlot,
}: ChartCardProps) {
  return (
    <Card className={cn("rounded-[var(--radius-lg)] border-[color:var(--chart-panel-border)] bg-[color:var(--chart-panel-bg)] p-5", className)}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium text-[color:var(--chart-title)]">{title}</h3>
          {description ? (
            <p className="mt-1 text-xs text-[color:var(--chart-subtitle)]">{description}</p>
          ) : null}
        </div>
        {headerSlot}
      </div>
      <div className={cn("mt-4 h-72", contentClassName)}>{children}</div>
    </Card>
  );
}
