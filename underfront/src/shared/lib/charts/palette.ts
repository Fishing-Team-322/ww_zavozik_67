export const chartPalette = {
  blue: "var(--chart-series-primary)",
  cyan: "var(--chart-series-cyan)",
  violet: "var(--chart-series-violet)",
  emerald: "var(--chart-series-emerald)",
  amber: "var(--chart-series-amber)",
  rose: "var(--chart-series-rose)",
  slate: "var(--chart-series-slate)",
  grid: "var(--chart-grid)",
} as const;

export const statusPalette: Record<string, string> = {
  paid: chartPalette.emerald,
  processing: chartPalette.amber,
  planned: chartPalette.blue,
  approved: chartPalette.cyan,
  rejected: chartPalette.rose,
  open: chartPalette.rose,
  in_review: chartPalette.amber,
  resolved: chartPalette.emerald,
};
