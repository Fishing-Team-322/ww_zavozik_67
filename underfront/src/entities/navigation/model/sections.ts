export const sections = ["transactions", "forecast", "scenarios", "risks", "calendar", "sources"] as const;

export type Section = (typeof sections)[number];
