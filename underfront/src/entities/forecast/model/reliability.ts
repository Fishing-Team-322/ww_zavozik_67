import type { Forecast, Gap } from "@/src/shared/api";

export function forecastReliability(forecast: Forecast, today = new Date().toISOString().slice(0, 10)) {
  const age = Math.round((Date.parse(today) - Date.parse(forecast.as_of)) / 86400000);
  const stale = age > 7 || forecast.warnings.includes("stale_statement_forecast_starts_after_data_as_of");
  const future = age < 0;
  const limited = forecast.fallback_used || forecast.low_confidence || forecast.warnings.includes("incomplete_history");
  const unconfirmed = forecast.unconfirmed_recurring ?? 0;
  return {
    age, stale, future, limited, unconfirmed,
    probabilityAvailable: forecast.probability_reliable !== false && !stale && !future && !limited,
    spendingAvailable: forecast.spending_available !== false && !stale && !future && !limited && unconfirmed === 0,
    end: forecast.forecast_end ?? forecast.points.at(-1)?.date ?? forecast.as_of,
  };
}

export function riskProbability(gap: Gap, forecast: Forecast) {
  return forecastReliability(forecast).probabilityAvailable && gap.probability_reliable !== false && Number.isFinite(gap.probability)
    ? gap.probability : null;
}

export function riskProbabilityText(gap: Gap, forecast: Forecast) {
  const value = riskProbability(gap, forecast);
  return value === null ? "Точная вероятность недоступна" : `${Math.round(value * 100)}% · оценка, не гарантия`;
}

export function gapAmount(gap: Pick<Gap, "shortfall" | "shortfall_p90">) {
  return gap.shortfall > 0
    ? { amount: gap.shortfall, label: "Нехватка по базовому прогнозу" }
    : gap.shortfall_p90 > 0
      ? { amount: gap.shortfall_p90, label: "Нехватка в неблагоприятном варианте" }
      : { amount: null, label: "Сумма нехватки не определена" };
}
