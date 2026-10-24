import { type ReactNode } from "react";

export type ChartDataPoint = Record<string, string | number | null | undefined>;

export type ChartSeriesConfig = {
  key: string;
  name: string;
  color: string;
  type?: "line" | "area" | "bar";
  formatter?: (value: number) => string;
};

export type ChartStateProps = {
  loading?: boolean;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  loadingFallback?: ReactNode;
};
