export type ClassValue =
  | string
  | number
  | null
  | undefined
  | boolean
  | ClassValue[]
  | Record<string, boolean | null | undefined>;

/**
 * Назначение функции: Выполняет операцию `clsx` для объекта «результат операции `clsx`»; возвращает `string`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
function clsx(...inputs: ClassValue[]): string {
  const result: string[] = [];

  for (const input of inputs) {
    if (!input) continue;

    if (typeof input === "string" || typeof input === "number") {
      result.push(String(input));
      continue;
    }

    if (Array.isArray(input)) {
      const nested = clsx(...input);
      if (nested) result.push(nested);
      continue;
    }

    if (typeof input === "object") {
      for (const key in input) {
        if (input[key]) result.push(key);
      }
    }
  }

  return result.join(" ");
}

/**
 * Назначение функции: Выполняет операцию `twMerge` для объекта «результат операции `twMerge`»; возвращает `string`.
 * Зачем используется: Выносит общий механизм из страниц и обработчиков.
 */
function twMerge(className: string): string {
  return className.replace(/\s+/g, " ").trim();
}

/**
 * Назначение функции: Объединяет переданные CSS-классы с учётом условных значений.
 * Зачем используется: Позволяет компонентам собирать стили без повторяющихся ручных проверок.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(...inputs));
}
