import { type ChartStateProps } from "./chart.types";

/**
 * Назначение функции: Возвращает данные объекта «диаграмма»; операция `getIsChartEmpty`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function getIsChartEmpty<Data extends unknown[]>(
  data: Data,
  isEmpty?: boolean
) {
  if (typeof isEmpty === "boolean") {
    return isEmpty;
  }

  return !data.length;
}

/**
 * Назначение функции: Определяет данные объекта «диаграмма»; операция `resolveChartState`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function resolveChartState<Data extends unknown[]>(
  data: Data,
  state: ChartStateProps
) {
  return {
    loading: Boolean(state.loading),
    isEmpty: getIsChartEmpty(data, state.isEmpty),
    emptyTitle: state.emptyTitle,
    emptyDescription: state.emptyDescription,
    loadingFallback: state.loadingFallback,
  };
}
