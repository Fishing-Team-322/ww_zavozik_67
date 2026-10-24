import { daysBetween, formatGapDate, type GapForecast } from "@/src/entities/cash-gap";
import { formatRub } from "@/src/shared/lib/charts";
import { gapMuted, gapPanel } from "./styles";

export interface CashGapSummaryProps {
  forecast: GapForecast;
  asOf: string;
  probability: number | null;
  probabilitySource: "mock" | "model";
  scenarioLabel?: string;
}

export function CashGapSummary({ forecast, asOf, probability, probabilitySource, scenarioLabel = "Базовый прогноз" }: CashGapSummaryProps) {
  const days = forecast.firstGapDate ? daysBetween(asOf, forecast.firstGapDate) : null;
  const metrics = [
    { label: "Первый разрыв", value: forecast.firstGapDate ? formatGapDate(forecast.firstGapDate, true) : "Не ожидается" },
    { label: "До разрыва от даты расчёта", value: days === null ? "—" : days < 0 ? "Уже наступил" : days === 0 ? "В день расчёта" : `${days} дн.` },
    { label: probabilitySource === "mock" ? "Вероятность · mock" : "Вероятность модели", value: probability === null ? "Нет оценки" : `${probability}%` },
    { label: "Минимальный остаток", value: formatRub(forecast.minimum), danger: forecast.minimum < 0 },
  ];
  return <section className={`${gapPanel} grid divide-y divide-[color:var(--border)] sm:grid-cols-[220px_minmax(0,1fr)] sm:divide-x sm:divide-y-0`} aria-label="Сводка кассового разрыва">
    <div className="px-4 py-4">
      <div className="flex items-center justify-between gap-2"><p className={gapMuted}>Максимальная нехватка</p><span className={`text-[12px] font-medium ${forecast.maximumShortfall ? "text-[color:var(--danger)]" : "text-[color:var(--accent)]"}`}>{forecast.maximumShortfall ? "Опасно" : "Устойчиво"}</span></div>
      <p className={`mt-2 text-[24px] font-semibold leading-7 tracking-tight tabular-nums ${forecast.maximumShortfall ? "text-[color:var(--danger)]" : "text-[color:var(--accent)]"}`}>{formatRub(forecast.maximumShortfall)}</p>
      <p className={`mt-1 ${gapMuted}`}>{scenarioLabel} · {forecast.shortfallDays} дн. с нехваткой</p>
    </div>
    <dl className="grid grid-cols-2 gap-x-4 gap-y-4 px-4 py-4 xl:grid-cols-4 xl:items-center">
      {metrics.map((metric) => <div key={metric.label} className="min-w-0"><dt className={gapMuted}>{metric.label}</dt><dd className={`mt-1 text-[15px] font-medium leading-5 tabular-nums ${metric.danger ? "text-[color:var(--danger)]" : "text-[color:var(--nav-item-active-text)]"}`}>{metric.value}</dd></div>)}
    </dl>
  </section>;
}
