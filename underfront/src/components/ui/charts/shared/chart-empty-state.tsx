import { EmptyState } from "@/src/components/ui/empty-state";

type ChartEmptyStateProps = {
  title?: string;
  description?: string;
};

/**
 * Назначение функции: Отображает компонент `ChartEmptyState` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function ChartEmptyState({
  title = "Нет данных",
  description = "Данные для графика пока отсутствуют",
}: ChartEmptyStateProps) {
  return <EmptyState title={title} description={description} className="h-full" />;
}
