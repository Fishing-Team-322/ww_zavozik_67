import type { Schemas } from "@/src/shared/api";
export function planFactSeries(
  rows: Schemas["PlanFactPoint"][],
  direction: "in" | "out" | "net",
) {
  return rows.map((row) => ({
    date: row.period,
    plan:
      direction === "net"
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
