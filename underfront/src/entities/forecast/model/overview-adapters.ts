import type { Forecast, Schemas } from "@/src/shared/api";

type Comparison = Schemas["ScenarioComparison"];
type OverviewPoint = { date: string; base: number; actual?: number; p10: number; p50: number; p90: number; delay?: number; downturn?: number };

// Never combine a refreshed scenario with an older dashboard or another horizon.
function sameBase(base: Forecast, comparison: Comparison) {
  return base.as_of === comparison.base.as_of && base.horizon === comparison.base.horizon &&
    base.opening_balance === comparison.base.opening_balance &&
    base.points.length === comparison.base.points.length &&
    base.points.every((point, i) => point.date === comparison.base.points[i].date && point.p50 === comparison.base.points[i].p50);
}

export function overviewForecastPoints(base: Forecast, delay?: Comparison | null, downturn?: Comparison | null): OverviewPoint[] {
  const output: OverviewPoint[] = [{ date: base.as_of, base: base.opening_balance, actual: base.opening_balance, p10: base.opening_balance, p50: base.opening_balance, p90: base.opening_balance },
    ...base.points.map(point => ({ date: point.date, base: point.p50, p10: point.p10, p50: point.p50, p90: point.p90 }))];
  for (const [key, comparison] of [["delay", delay], ["downturn", downturn]] as const) {
    if (!comparison || !sameBase(base, comparison) || comparison.scenario.points.length !== base.points.length ||
      !comparison.scenario.points.every((point, i) => point.date === base.points[i].date && Number.isFinite(point.p50))) continue;
    output[0][key] = base.opening_balance;
    comparison.scenario.points.forEach((point, i) => { output[i + 1][key] = point.p50; });
  }
  return output;
}

export function overviewDelayStep(events: Schemas["PlannedEvent"][], asOf: string, through: string): Schemas["ScenarioStep"] | null {
  const receipt = events.filter(event => event.status === "expected" && event.direction === "in" &&
    event.date > asOf && event.date <= through && event.counterparty.id && event.probability > 0 && event.forecast_eligible !== false)
    .sort((a, b) => b.amount - a.amount || a.id.localeCompare(b.id))[0];
  return receipt ? { kind: "delay_counterparty", counterparty_id: receipt.counterparty.id!, delay_days: 14 } : null;
}
