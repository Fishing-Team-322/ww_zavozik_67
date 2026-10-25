"use client";

import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, LineChart, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { money } from "./finance-utils";

type Backtest = {
  as_of: string; from: string; to: string; computed_at: string;
  model_used: string; model_version: string; fallback_used: boolean; low_confidence: boolean;
  samples: number; excluded_days: number; covered_days: number; mean_absolute_error: number | null;
  history_days: number; withheld_operations: number; history_sha256: string; withheld_sha256: string;
  notice: string;
  points: {date: string; forecast: number; actual: number | null; lower: number; upper: number; absolute_error: number | null}[];
};

export function HistoricalBacktest({companyId}: {companyId: string}) {
  const report = useApiResource<Backtest>(`/v1/companies/${companyId}/plan-fact/backtest`);
  const data = report.data;
  return <SectionCard className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><ContentHeading level={2}>Проверка прогноза на прошлых данных</ContentHeading><Button variant="outline" onClick={report.refresh} disabled={report.loading}>Пересчитать проверку</Button></div>
    <ContentText variant="description">Последние 30 дней выписки скрываем от модели. Строим прогноз по более ранней истории и сравниваем с фактическим остатком.</ContentText>
    <FinanceState loading={report.loading} error={report.error} retry={report.refresh}/>
    {data && <>
      <ContentText variant="body">История до {data.as_of} · проверка {data.from} — {data.to} · {data.history_days} дней истории</ContentText>
      <div className="grid gap-4 text-sm sm:grid-cols-3">
        <div><span className="text-[color:var(--text-secondary)]">Средняя ошибка остатка</span><strong className="mt-1 block tabular-nums">{money(data.mean_absolute_error)}</strong></div>
        <div><span className="text-[color:var(--text-secondary)]">Дней с подтверждённым фактом</span><strong className="mt-1 block">{data.samples} из 30</strong></div>
        <div><span className="text-[color:var(--text-secondary)]">Факт внутри диапазона p10–p90</span><strong className="mt-1 block">{data.covered_days} из {data.samples} дней</strong></div>
      </div>
      <div className="h-80" aria-label="Сравнение исторического прогноза с фактом"><LineChart data={data.points} xKey="date" series={[{key:"forecast",name:"Прогноз p50",color:"var(--accent)",formatter:money},{key:"actual",name:"Фактический остаток",color:"var(--warning)",formatter:money}]} /></div>
      <ContentText variant="description">Модель: {data.model_used} · {data.fallback_used ? "упрощённый расчёт" : "основная модель"}{data.low_confidence ? " · надёжность ограничена" : ""}. Исключено дней без подтверждённого факта: {data.excluded_days}.</ContentText>
      <ContentText variant="description">{data.notice}</ContentText>
      <details><summary className="cursor-pointer text-sm">Дневная сверка и происхождение расчёта</summary>
        <ContentText variant="description" className="my-3 break-all">Рассчитано: {data.computed_at} · версия {data.model_version}. Отложено операций: {data.withheld_operations}. SHA истории: {data.history_sha256}; SHA отложенных операций: {data.withheld_sha256}.</ContentText>
        <Table><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead numeric>Прогноз</TableHead><TableHead numeric>Факт</TableHead><TableHead numeric>Абсолютная ошибка</TableHead></TableRow></TableHeader><TableBody>{data.points.map(point=><TableRow key={point.date}><TableCell>{point.date}</TableCell><TableCell numeric>{money(point.forecast)}</TableCell><TableCell numeric>{money(point.actual)}</TableCell><TableCell numeric>{money(point.absolute_error)}</TableCell></TableRow>)}</TableBody></Table>
      </details>
    </>}
  </SectionCard>;
}
