type SearchableNavigationItem = {
  label: string;
  href: string;
  section?: string;
  disabled?: boolean;
};

function normalize(value: string): string {
  return value.toLocaleLowerCase("ru-RU").replace(/ё/g, "е").replace(/[^a-zа-я0-9]+/g, " ").trim();
}

/** Search the current navigation, preserving its labels, routes and display order. */
export function searchNavigation<T extends SearchableNavigationItem>(items: readonly T[], query: string): T[] {
  const normalized = normalize(query);
  if (!normalized) return [];
  const terms = normalized.split(/\s+/);
  const seen = new Set<string>();
  return items.filter(item => {
    if (item.disabled || item.section === "Development" || item.section === "Разработка" ||
      !item.href.startsWith("/") || item.href.startsWith("//") || seen.has(item.href)) return false;
    const label = normalize(item.label);
    if (!terms.every(term => label.includes(term))) return false;
    seen.add(item.href);
    return true;
  });
}
