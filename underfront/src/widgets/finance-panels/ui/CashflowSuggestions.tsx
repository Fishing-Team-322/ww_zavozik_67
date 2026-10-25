"use client";

import Link from "next/link";
import type { Gap, Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { Button } from "@/src/shared/ui/button";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowSuggestion } from "./CashflowSuggestion";

export function CashflowSuggestions({ companyId, gap, horizon }: { companyId: string; gap: Gap; horizon: number }) {
  const detail = useApiResource<Schemas["GapDetail"]>(`/v1/companies/${companyId}/gaps/${encodeURIComponent(gap.id)}?horizon=${horizon}`);
  const actions = detail.data?.actions ?? [];
  return <section className="mt-5 space-y-3" aria-label="Подсказки по денежному потоку">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><ContentHeading level={2}>Подсказки по денежному потоку</ContentHeading><ContentText variant="description" tone="muted">Варианты по вашим платежам. Эффект каждого рассчитан отдельно.</ContentText></div>
      <Link href={`/risks?gap=${encodeURIComponent(gap.id)}&horizon=${horizon}`} className="text-sm text-[color:var(--accent)] underline">Сравнить и выбрать действия</Link>
    </div>
    {detail.loading && <p role="status" className="text-sm">Рассчитываем подсказки…</p>}
    {detail.error && <div role="alert" className="text-sm">Не удалось загрузить подсказки. <Button variant="ghost" onClick={detail.refresh}>Повторить</Button></div>}
    {!detail.loading && !detail.error && actions.length === 0 && <ContentText variant="description" tone="muted">Для подсказок проверьте планы и загрузите актуальную выписку.</ContentText>}
    <div className="grid items-start gap-4 lg:grid-cols-3">{actions.slice(0, 3).map(action => <SectionCard key={action.id} className="space-y-3"><ContentHeading level={3}>{action.title}</ContentHeading><CashflowSuggestion action={action} compact /></SectionCard>)}</div>
  </section>;
}
