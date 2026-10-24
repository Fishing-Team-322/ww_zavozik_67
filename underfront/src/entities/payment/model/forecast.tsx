import type { MonthForecast, PaymentEvent } from "./types";

export function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function parseDate(key: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

export function addMonths(date: Date, count: number): Date {
  return new Date(date.getFullYear(), date.getMonth() + count, 1);
}

export function addDays(date: Date, count: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + count);
}

export function formatMoney(amount: number): string {
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(amount)} ₽`;
}

export function formatCompactMoney(amount: number): string {
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(amount / 1_000_000)} млн`;
  if (abs >= 1_000) return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(amount / 1_000)} тыс.`;
  return new Intl.NumberFormat("ru-RU").format(amount);
}

function signedAmount(event: PaymentEvent): number {
  if (event.status === "cancelled" || (event.status === "overdue" && event.direction === "income")) return 0;
  return event.direction === "income" ? event.amount : -event.amount;
}

/** Детерминированная локальная симуляция: полные суммы событий по датам, без ML и взвешивания вероятности. */
export function calculateMonthForecast(
  month: Date,
  anchorMonth: Date,
  anchorOpening: number,
  events: readonly PaymentEvent[],
): MonthForecast {
  const start = monthStart(month);
  const anchor = monthStart(anchorMonth);
  const startKey = dateKey(start);
  const anchorKey = dateKey(anchor);
  let opening = anchorOpening;
  for (const event of events) {
    if (startKey > anchorKey && event.date >= anchorKey && event.date < startKey) opening += signedAmount(event);
    if (startKey < anchorKey && event.date >= startKey && event.date < anchorKey) opening -= signedAmount(event);
  }

  const days = [] as MonthForecast["days"];
  let balance = opening;
  let income = 0;
  let expense = 0;
  let minimum = opening;
  const shortfallDates: string[] = [];
  const count = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate();
  for (let number = 1; number <= count; number++) {
    const key = dateKey(new Date(start.getFullYear(), start.getMonth(), number));
    const dayEvents = events.filter((event) => event.date === key);
    const dayIncome = dayEvents.filter((event) => event.direction === "income" && event.status !== "cancelled" && event.status !== "overdue").reduce((sum, event) => sum + event.amount, 0);
    const dayExpense = dayEvents.filter((event) => event.direction === "expense" && event.status !== "cancelled").reduce((sum, event) => sum + event.amount, 0);
    const dayOpening = balance;
    balance += dayIncome - dayExpense;
    income += dayIncome;
    expense += dayExpense;
    minimum = Math.min(minimum, balance);
    if (balance < 0) shortfallDates.push(key);
    days.push({ date: key, opening: dayOpening, income: dayIncome, expense: dayExpense, closing: balance, events: dayEvents });
  }
  return { days, opening, closing: balance, income, expense, minimum, shortfallDates };
}
