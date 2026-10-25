import type { Forecast } from "@/src/shared/api";
import { dayOffset } from "./dataset";
import type { ActualDay, CheckpointMetrics, ControlOperation } from "./types";

/** Reconcile against all bank movements, including financing. Unknown intervals stay unknown. */
export function actualBalances(operations: ControlOperation[]): ActualDay[] {
  if (!operations.length) return [];
  const sorted = [...operations].sort((a, b) => a.date.localeCompare(b.date));
  const from = sorted[0].date, to = sorted.at(-1)!.date;
  const days: { date: string; balance: number | null; missing: boolean; conflict: boolean; net: number; count: number }[] = [];
  const byDate = new Map<string, typeof days[number]>();
  for (let date = from; date <= to; date = dayOffset(date, 1)) {
    const row = { date, balance: null as number | null, missing: false, conflict: false, net: 0, count: 0 };
    days.push(row); byDate.set(date, row);
  }
  for (const op of sorted) {
    const row = byDate.get(op.date)!;
    row.net += op.direction === "in" ? op.amount : -op.amount; row.count++;
    if (op.balance !== null) {
      if (row.balance !== null && Math.abs(row.balance - op.balance) > .011) row.conflict = true;
      row.balance = op.balance;
    }
  }
  let anchor = -1, movement = 0;
  for (let index = 0; index < days.length; index++) {
    const row = days[index]; movement += row.net;
    if (row.conflict) { row.missing = true; row.balance = null; anchor = -1; movement = 0; continue; }
    if (row.balance === null) continue;
    if (anchor >= 0 && Math.abs(row.balance - days[anchor].balance! - movement) > .011) {
      for (let gap = anchor + 1; gap <= index; gap++) days[gap].missing = true;
    }
    anchor = index; movement = 0;
  }
  return days.map(row => {
    if (row.missing) { return { date: row.date, balance: null, observed: false, reason: row.conflict ? "conflicting_balances" : "unreconciled_interval" }; }
    return { date: row.date, balance: row.balance, observed: row.balance !== null, ...(row.balance === null ? { reason: "missing_balance" } : {}) };
  });
}

export function evaluateForecast(forecast: Forecast, truth: ActualDay[], reserve: number, enabled: boolean): CheckpointMetrics {
  const byDate = new Map(truth.map(day => [day.date, day]));
  const points = forecast.points.map(point => {
    const day = byDate.get(point.date), actual = enabled && day?.observed ? day.balance : null;
    return { date: point.date, predicted: point.p50, actual, lower: point.p10, upper: point.p90, observed: actual !== null };
  });
  const observed = points.filter(point => point.observed);
  let absolute = 0, squared = 0, denominator = 0, inside = 0, tp = 0, fp = 0, fn = 0, tn = 0;
  for (const point of observed) {
    const error = point.predicted - point.actual!;
    absolute += Math.abs(error); squared += error * error; denominator += Math.abs(point.actual!);
    if (point.actual! >= point.lower && point.actual! <= point.upper) inside++;
    const predictedGap = point.predicted < reserve, actualGap = point.actual! < reserve;
    if (predictedGap && actualGap) tp++; else if (predictedGap) fp++; else if (actualGap) fn++; else tn++;
  }
  const n = observed.length;
  return { truthBasis: "explicit_nonconflicting_eod", samples: n, excluded: enabled ? points.length - n : 0, mae: n ? absolute / n : null, mse: n ? squared / n : null, rmse: n ? Math.sqrt(squared / n) : null,
    wape: n && denominator ? absolute / denominator : null, coverage: n ? inside / n : null,
    accuracy: n ? (tp + tn) / n : null, precision: tp + fp ? tp / (tp + fp) : null, recall: tp + fn ? tp / (tp + fn) : null,
    f1: 2 * tp + fp + fn ? 2 * tp / (2 * tp + fp + fn) : null, confusion: n ? { tp, fp, fn, tn } : null,
    classificationBasis: "median_balance_below_reserve", points };
}
