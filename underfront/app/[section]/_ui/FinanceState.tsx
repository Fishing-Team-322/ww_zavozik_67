import Link from "next/link";
import { Button } from "@/src/shared/ui/button";
import type { Forecast } from "@/src/shared/api";
import { fallbackNotice } from "@/src/entities/forecast";

export function FinanceState({
  loading,
  error,
  retry,
}: {
  loading: boolean;
  error: string | null;
  retry: () => void;
}) {
  return (
    <>
      {loading && (
        <p
          role="status"
          className="mb-4 text-sm text-[color:var(--text-secondary)]"
        >
          Загружаем данные…
        </p>
      )}
      {error && (
        <div
          role="alert"
          className="mb-4 space-y-3 rounded-lg border border-[color:var(--border)] p-4"
        >
          <p className="text-sm text-[color:var(--danger)]">{error}</p>
          <div className="flex items-center gap-5">
            <Button variant="outline" onClick={retry}>
              Повторить
            </Button>
            <Link
              className="text-sm text-[color:var(--accent)]"
              href="/sources"
            >
              Источники данных
            </Link>
          </div>
        </div>
      )}
    </>
  );
}
export function ForecastNotice({ forecast }: { forecast: Forecast | null }) {
  if (!forecast) return null;
  return (
    <div className="mb-4 space-y-1 text-xs text-[color:var(--text-secondary)]">
      <p>
        Данные на {forecast.as_of} · модель {forecast.model_used}
      </p>
      {forecast.fallback_used && (
        <p role="status">
          {fallbackNotice(forecast.warnings)}
        </p>
      )}
      {forecast.low_confidence && (
        <p>Надёжность оценки ограничена полнотой истории.</p>
      )}
      {forecast.warnings.includes("overdue_additional_expenses_carried_forward") && (
        <p>
          Неоплаченные дополнительные расходы учтены в первый день прогноза.
          Проверьте оплату или уточните срок в календаре.
        </p>
      )}
      {forecast.warnings.includes(
        "stale_statement_forecast_starts_after_data_as_of",
      ) && (
        <p>
          Выписка устарела: прогноз начинается после последней даты данных.
          Загрузите свежую выписку.
        </p>
      )}
    </div>
  );
}
