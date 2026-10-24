// Shared RU display-date helpers ("ДД.ММ.ГГГГ" <-> Date). Single source of
// truth for the date-field input mask and any filter logic that needs to
// parse the same string shape (e.g. date-range filters) without pulling in
// the (client-only) date-field component.

/**
 * Назначение функции: Shared RU display-date helpers ("ДД.ММ.ГГГГ" <-> Date). Single source of truth for the date-field input mask and any filter logic that needs to parse the same string shape (e.g. date-range filters) without pulling in the (client-only) date-field component.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function formatRuDate(date: Date): string {
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear()).padStart(4, "0");

  return `${day}.${month}.${year}`;
}

/**
 * Назначение функции: Разбирает данные объекта «дата»; операция `parseRuDate`.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function parseRuDate(value: string): Date | null {
  if (!/^\d{2}\.\d{2}\.\d{4}$/.test(value)) return null;

  const [dayString, monthString, yearString] = value.split(".");
  const day = Number(dayString);
  const month = Number(monthString);
  const year = Number(yearString);

  if (!day || !month || !year) return null;

  const date = new Date(year, month - 1, day);

  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  return date;
}

/** Start-of-day bound for a "from" filter, parsed from a "ДД.ММ.ГГГГ" string. */
/**
 * Назначение функции: Start-of-day bound for a "from" filter, parsed from a "ДД.ММ.ГГГГ" string.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function parseRuDateRangeStart(value: string): Date | null {
  const date = parseRuDate(value);
  if (!date) return null;
  date.setHours(0, 0, 0, 0);
  return date;
}

/** End-of-day bound for a "to" filter, parsed from a "ДД.ММ.ГГГГ" string. */
/**
 * Назначение функции: End-of-day bound for a "to" filter, parsed from a "ДД.ММ.ГГГГ" string.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function parseRuDateRangeEnd(value: string): Date | null {
  const date = parseRuDate(value);
  if (!date) return null;
  date.setHours(23, 59, 59, 999);
  return date;
}
