export const sections = ["transactions", "forecast", "scenarios", "risks", "calendar"] as const;

export type Section = (typeof sections)[number];
