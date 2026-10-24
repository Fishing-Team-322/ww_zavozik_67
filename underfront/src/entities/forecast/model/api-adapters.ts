import type { Forecast, Gap, Schemas } from "@/src/shared/api";

export type ChartDay = {
  date: string;
  actual?: number | null;
  baseline?: number | null;
  scenario?: number | null;
  lowerBound?: number | null;
  upperBound?: number | null;
  events?: string[];
};
export function chartDays(
  base: Forecast,
  scenario?: Pick<Forecast, "points"> | null,
): ChartDay[] {
  const days = new Map<string, ChartDay>();
  for (const point of base.history)
    days.set(point.date, { date: point.date, actual: point.balance });
  for (const point of base.points)
    days.set(point.date, {
      ...days.get(point.date),
      date: point.date,
      baseline: point.p50,
      lowerBound: point.p10,
      upperBound: point.p90,
    });
  for (const point of scenario?.points || [])
    days.set(point.date, {
      ...days.get(point.date),
      date: point.date,
      scenario: point.p50,
    });
  for (const marker of base.markers) {
    const day = days.get(marker.date);
    if (day) day.events = [...(day.events || []), marker.title];
  }
  return [...days.values()].sort((a, b) => a.date.localeCompare(b.date));
}
export const rubles = (value: number) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 2,
  }).format(value);
export const displayDate = (date: string) =>
  new Date(`${date.slice(0, 10)}T00:00:00Z`).toLocaleDateString("ru-RU", {
    timeZone: "UTC",
  });
export function riskView(
  gap: Gap,
  causes: Schemas["GapDetail"]["causes"] = [],
) {
  return {
    id: gap.id,
    date: displayDate(gap.date),
    deficit: gap.shortfall,
    probability: gap.probability,
    reasons: causes.map((cause) => `${cause.title}: ${rubles(cause.amount)}`),
  };
}
export function calendarEvent(event: Schemas["PlannedEvent"]) {
  return {
    ...event,
    direction:
      event.direction === "in" ? ("income" as const) : ("expense" as const),
    status: event.status === "missed" ? "overdue" : event.status,
    counterparty: event.counterparty.name,
    manual: event.source === "manual",
  };
}
