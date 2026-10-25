import Link from "next/link";
import { Button } from "@/src/shared/ui/button";
import type { Forecast } from "@/src/shared/api";
import { fallbackNotice, forecastReliability } from "@/src/entities/forecast";

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
  const reliability = forecastReliability(forecast);
  return (
    <div className="mb-4 space-y-1 text-xs text-[color:var(--text-secondary)]">
      <p>
        Остаток подтверждён на {forecast.as_of} · прогноз до {reliability.end}
      </p>
      {forecast.fallback_used && (
        <p role="status">
          {fallbackNotice(forecast.warnings)}
        </p>
      )}
      {forecast.low_confidence && (
        <p>Надёжность оценки ограничена качеством данных и допущениями расчёта.</p>
      )}
      {forecast.warnings.includes("overdue_additional_expenses_carried_forward") && (
        <p>
          Неоплаченные дополнительные расходы учтены в первый день прогноза.
          Проверьте оплату или уточните срок в календаре.
        </p>
      )}
      {(reliability.stale || reliability.future) && <p role="alert" className="rounded-md border border-[color:var(--warning)] p-3 font-semibold">{reliability.future ? "В выписке есть будущие даты." : `Выписке ${reliability.age} дн. Текущий остаток неизвестен.`} Рекомендация о расходах недоступна. <Link href="/sources" className="underline">Загрузите актуальную выписку</Link>.</p>}
      {reliability.unconfirmed > 0 && <p role="status">План обязательств ещё не проверен: найдено платежей без подтверждения — {reliability.unconfirmed}. <Link href="/recurring" className="underline">Проверить расписание</Link>. Уточните также зарплату, налоги и крупные поступления.</p>}
      {reliability.limited && <p>Точная вероятность риска и рекомендация о расходах недоступны при ограниченной надёжности прогноза.</p>}
    </div>
  );
}
