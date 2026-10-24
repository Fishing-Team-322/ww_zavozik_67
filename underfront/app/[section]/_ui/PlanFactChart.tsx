"use client";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Schemas } from "@/src/shared/api";
import { planFactSeries } from "@/src/entities/forecast/model/plan-fact";
import { money } from "./finance-utils";
export function PlanFactChart({
  rows,
  direction,
}: {
  rows: Schemas["PlanFactPoint"][];
  direction: "in" | "out" | "net";
}) {
  return (
    <div
      className="h-80 min-w-0"
      role="img"
      aria-label="График плана и факта: пропуски выписки не заменяются нулём"
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <LineChart
          data={planFactSeries(rows, direction)}
          margin={{ top: 10, right: 20, left: 12, bottom: 10 }}
        >
          <CartesianGrid
            vertical={false}
            strokeDasharray="3 4"
            stroke="var(--border)"
          />
          <XAxis
            dataKey="date"
            minTickGap={30}
            tick={{ fontSize: 11 }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            tick={{ fontSize: 11 }}
            tickFormatter={(value) => `${Math.round(Number(value) / 1000)}к`}
          />
          <Tooltip formatter={(value) => money(Number(value))} />
          <Legend />
          <ReferenceLine y={0} stroke="var(--text-muted)" />
          <Line
            dataKey="plan"
            name="План"
            stroke="var(--accent)"
            strokeDasharray="5 4"
            dot={false}
            connectNulls={false}
          />
          <Line
            dataKey="fact"
            name="Факт"
            stroke="var(--chart-series-primary)"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
