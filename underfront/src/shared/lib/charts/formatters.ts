const rubFormatter = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  maximumFractionDigits: 0,
});

/**
 * Назначение функции: Форматирует данные объекта «формат представления»; операция `formatRub`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
export function formatRub(value: number) {
  return rubFormatter.format(value);
}

/**
 * Назначение функции: Форматирует данные объекта «формат представления»; операция `formatCompactRub`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
export function formatCompactRub(value: number) {
  if (value >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)} млрд ₽`;
  }

  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)} млн ₽`;
  }

  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)} тыс ₽`;
  }

  return `${value} ₽`;
}

/**
 * Назначение функции: Форматирует данные объекта «формат представления»; операция `formatMonthLabel`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
export function formatMonthLabel(dateIso: string) {
  return new Date(dateIso).toLocaleDateString("ru-RU", { month: "short" });
}

/**
 * Назначение функции: Выполняет операцию `humanizeStatus` для объекта «состояние». Возвращает результаты выражений: `labels[status] ?? status`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
export function humanizeStatus(status: string) {
  const labels: Record<string, string> = {
    planned: "План",
    approved: "Согласовано",
    processing: "В обработке",
    paid: "Оплачено",
    rejected: "Отклонено",
    open: "Открыт",
    in_review: "На рассмотрении",
    resolved: "Решен",
  };

  return labels[status] ?? status;
}
