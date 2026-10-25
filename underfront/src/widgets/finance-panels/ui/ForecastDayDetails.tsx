"use client";

import { contentTypography } from "@/src/shared/ui/content";
import { displayDate, rubles } from "@/src/entities/forecast";
import type { Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, ErrorState } from "@/src/shared/ui";

type Props = { companyId: string; date: string; horizon: string | number; scenario?: string };

/** Shared day drill-down for Overview and the full forecast. */
export function ForecastDayDetails({ companyId, date, horizon, scenario }: Props) {
  const query = new URLSearchParams({ horizon: String(horizon), ...(scenario ? { scenario } : {}) });
  const detail = useApiResource<Schemas["ForecastDay"]>(
    `/v1/companies/${encodeURIComponent(companyId)}/forecast/days/${encodeURIComponent(date)}?${query}`,
  );
  return <div className={`mt-3 space-y-5 ${contentTypography.body}`}>
    {detail.loading && <p role="status">Загружаем подробности дня…</p>}
    {detail.error && <ErrorState description={detail.error} action={<Button variant="outline" onClick={detail.refresh}>Повторить</Button>} />}
    {detail.data && <>
      <div className="flex flex-wrap items-center gap-2 text-xs text-[color:var(--text-secondary)]">
        <span>{displayDate(detail.data.date)}</span>
        <span aria-hidden="true">·</span>
        <span>{detail.data.is_workday ? "Рабочий день" : "Выходной день"}</span>
      </div>
      <section className="border border-[color:var(--border)] bg-[color:var(--surface-subtle)] p-4">
        <p className="text-xs text-[color:var(--text-secondary)]">Ожидаемый остаток к концу дня</p>
        <p className="mt-1 text-xl font-semibold tabular-nums text-[color:var(--text-primary)]">{rubles(detail.data.p50)}</p>
        <p className="mt-1 text-xs text-[color:var(--text-secondary)]">Медианный прогноз (p50)</p>
      </section>
      <section aria-label="Диапазон прогноза">
        <p className="mb-2 text-sm font-medium text-[color:var(--text-primary)]">Возможный диапазон остатка</p>
        <div className="grid grid-cols-2 gap-2">
          <div className="border border-[color:var(--border)] p-3">
            <p className="text-xs text-[color:var(--text-secondary)]">Нижняя оценка · p10</p>
            <p className="mt-1 font-medium tabular-nums text-[color:var(--text-primary)]">{rubles(detail.data.p10)}</p>
          </div>
          <div className="border border-[color:var(--border)] p-3">
            <p className="text-xs text-[color:var(--text-secondary)]">Верхняя оценка · p90</p>
            <p className="mt-1 font-medium tabular-nums text-[color:var(--text-primary)]">{rubles(detail.data.p90)}</p>
          </div>
        </div>
      </section>
      <section>
        <h3 className="text-sm font-medium text-[color:var(--text-primary)]">Что влияет на прогноз в этот день</h3>
        {detail.data.components.length ? (
          <ul className="mt-2 divide-y divide-[color:var(--border)] border-y border-[color:var(--border)]">
            {detail.data.components.map((part, index) => (
              <li key={`${part.kind}-${index}`} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-[color:var(--text-primary)]">{part.title}</p>
                  <p className="mt-0.5 text-xs text-[color:var(--text-secondary)]">Источник: {part.source}</p>
                </div>
                <span className="shrink-0 font-medium tabular-nums text-[color:var(--text-primary)]">{part.amount > 0 ? "+" : ""}{rubles(part.amount)}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-2 text-sm text-[color:var(--text-secondary)]">На этот день отдельные потоки не указаны.</p>}
        <p className="mt-2 text-xs text-[color:var(--text-secondary)]">Это средние потоки: их сумма может отличаться от изменения медианного остатка.</p>
      </section>
    </>}
  </div>;
}
