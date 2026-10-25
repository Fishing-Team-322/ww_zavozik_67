export const sections = ["transactions", "forecast", "scenarios", "risks", "calendar", "recurring", "documents", "taxes", "plan-fact", "counterparties", "notifications", "settings", "methodology"] as const;

export type Section = (typeof sections)[number];
