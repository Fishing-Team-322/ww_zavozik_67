import type { Schemas } from "@/src/shared/api";

export type SavedForecastChange = {
  gap_date: string | null;
  gap_date_before: string | null;
  probability_before: number | null;
  probability_after: number | null;
  probability_reliable_before?: boolean;
  probability_reliable_after?: boolean;
  revision_before: number | null;
  revision_after: number | null;
};

// Missing flags from an older API are unknown, never permission to show a percent.
export function planFactProbability(change: SavedForecastChange, side: "before" | "after") {
  const value = change[`probability_${side}`];
  return change[`probability_reliable_${side}`] === true && typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

export function planFactSeries(
  rows: Schemas["PlanFactPoint"][],
  direction: "in" | "out" | "net",
) {
  return rows.map((row) => ({
    date: row.period,
    plan:
      row.plan_available === false || row.plan_in === null || row.plan_out === null ? null : direction === "net"
        ? row.plan_in - row.plan_out
        : row[`plan_${direction}`],
    fact:
      !row.observed || row.fact_in === null || row.fact_out === null
        ? null
        : direction === "net"
          ? row.fact_in - row.fact_out
          : row[`fact_${direction}`],
    deviation: row.deviation,
  }));
}
