"use client";

import { contentTypography } from "@/src/shared/ui/content";
import { rubles } from "@/src/entities/forecast";
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
  return <div className={`mt-3 space-y-2 ${contentTypography.body}`}>
    {detail.loading && <p role="status">Загружаем подробности дня…</p>}
    {detail.error && <ErrorState description={detail.error} action={<Button variant="outline" onClick={detail.refresh}>Повторить</Button>} />}
    {detail.data && <>
      <p>{detail.data.date} · {detail.data.is_workday ? "Рабочий день" : "Выходной день"}</p>
      <p>Остаток p50: {rubles(detail.data.p50)}</p>
      <p>Коридор p10–p90: {rubles(detail.data.p10)} — {rubles(detail.data.p90)}</p>
      <p>Состав ожидаемого потока за день (средние потоки; сумма не равна изменению медианы остатка):</p>
      {detail.data.components.length ? detail.data.components.map((part, i) =>
        <p key={`${part.kind}-${i}`}>{part.title}: {rubles(part.amount)} · {part.source}</p>,
      ) : <p>Состав потока за этот день отсутствует.</p>}
    </>}
  </div>;
}
