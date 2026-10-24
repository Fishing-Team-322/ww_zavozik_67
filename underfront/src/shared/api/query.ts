/** Absent filters stay absent; false and zero are valid, distinct values. */
export function queryParams(values: Record<string, string | number | boolean | null | undefined>): URLSearchParams {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  return query;
}
