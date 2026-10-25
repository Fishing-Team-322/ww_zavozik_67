export function shiftScenarioDate(date: string, days: number) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  const value = new Date(`${date}T00:00:00Z`);
  if (!Number.isFinite(value.getTime()) || value.toISOString().slice(0, 10) !== date) return "";
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

export function scenarioWindowBounds(first: string, last: string, selectedStart: string) {
  const from = selectedStart || first;
  const to = shiftScenarioDate(from, 29);
  return { from, to, valid: Boolean(first && last && to && from >= first && to <= last), latestStart: shiftScenarioDate(last, -29), earliestEnd: shiftScenarioDate(first, 29) };
}
