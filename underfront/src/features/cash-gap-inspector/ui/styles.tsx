import { contentTypography } from "@/src/shared/ui/content";

export const gapPanel = "min-w-0 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)]";
export const gapHeading = `${contentTypography.section} text-[color:var(--text-primary)]`;
export const gapMuted = `${contentTypography.description} text-[color:var(--text-secondary)]`;
export const gapFocus = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)]";
export const sourceLabels = { bank: "Банковская выписка", invoice: "Счёт", contract: "Договор", recurring: "Регулярный платёж", tax: "Налоги", manual: "Ручной ввод" };
