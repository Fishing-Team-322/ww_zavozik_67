// Native economic groups stay separate from the forecast compatibility category.
export function discoveryLabel(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (row.status === "unknown") return "Группа не определена";
  if (row.status === "ambiguous") return "Группу нужно уточнить";
  if (row.status === "insufficient_text") return "Недостаточно данных для группы";
  if (row.status !== "assigned" && row.status !== "coarse_only") return null;
  const titles = [row.coarse_category_title, row.category_title].filter((s): s is string => typeof s === "string" && s.length > 0);
  return titles.length ? `Предварительная группа: ${[...new Set(titles)].join(" / ")}` : "Группу нужно уточнить";
}
