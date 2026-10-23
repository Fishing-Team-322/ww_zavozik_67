"use client";

import { useState } from "react";
import Link from "next/link";
import { CalendarDays, FileSpreadsheet, Search } from "lucide-react";
import { PageLayout, SectionCard } from "@/src/components/cabinet/shared";
import { CashflowForecastChart, DEFAULT_SCENARIO, RiskCard, ScenarioControls, type ScenarioParams } from "@/src/components/finance";
import { EmptyState, Input } from "@/src/components/ui";
import type { Section } from "@/src/lib/sections";

export function SectionView({ section }: { section: Section }) {
  const [query, setQuery] = useState("");
  const [scenario, setScenario] = useState<ScenarioParams>(DEFAULT_SCENARIO);
  const [filename, setFilename] = useState("");
  return (
    <PageLayout>

      {section === "transactions" && (
        <SectionCard className="p-5">
          <h2 className="mb-4 text-lg font-semibold">История операций</h2>
          <Input label="Поиск по операциям" placeholder="Контрагент или назначение" value={query} onChange={(event) => setQuery(event.target.value)} startAdornment={<Search size={16} />} containerClassName="max-w-sm" />
          <EmptyState className="mt-5" title="Операции не загружены" description={query ? "Подключите выписку, чтобы искать по операциям." : "Подключите выписку, чтобы увидеть поступления и расходы."} action={<Link href="/sources" className="font-semibold text-[color:var(--accent)]">Открыть источники данных →</Link>} />
        </SectionCard>
      )}

      {section === "forecast" && (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
          <SectionCard className="p-5"><h2 className="mb-1 text-lg font-semibold">Денежный остаток</h2><p className="mb-4 text-xs text-[color:var(--text-secondary)]">Факт, базовый и негативный сценарии · нулевая линия</p><CashflowForecastChart days={[]} /></SectionCard>
          <RiskCard risk={null} />
        </div>
      )}

      {section === "scenarios" && (
        <div className="grid items-start gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
          <ScenarioControls value={scenario} onChange={setScenario} />
          <SectionCard className="p-5"><h2 className="mb-1 text-lg font-semibold">Результат сценария</h2><p className="mb-4 text-xs text-[color:var(--text-secondary)]">Выбранные параметры будут отправляться на пересчёт после подключения API.</p><CashflowForecastChart days={[]} /></SectionCard>
        </div>
      )}

      {section === "risks" && (
        <div className="grid gap-4 lg:grid-cols-2"><RiskCard risk={null} /><EmptyState title="Периоды дефицита неизвестны" description="Загрузите данные и получите прогноз, чтобы увидеть даты, суммы и причины разрывов." /></div>
      )}

      {section === "calendar" && (
        <SectionCard className="p-5"><div className="mb-5 flex items-center gap-2"><CalendarDays size={20} aria-hidden="true" /><h2 className="text-lg font-semibold">Платёжный календарь</h2></div><EmptyState title="Платежи не загружены" description="После подключения источников здесь будут плановые поступления и списания по датам." /></SectionCard>
      )}

      {section === "sources" && (
        <SectionCard className="p-5"><div className="mb-5 flex items-center gap-2"><FileSpreadsheet size={20} aria-hidden="true" /><h2 className="text-lg font-semibold">Выписка</h2></div><label htmlFor="statement-file" className="mb-2 block text-sm font-medium">Выберите CSV-файл</label><input id="statement-file" type="file" accept=".csv,text/csv" className="block max-w-full text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-[color:var(--accent-soft)] file:px-4 file:py-2 file:font-semibold file:text-[color:var(--accent)]" onChange={(event) => setFilename(event.target.files?.[0]?.name ?? "")} /><p className="mt-3 text-sm text-[color:var(--text-secondary)]">{filename ? `Выбран файл: ${filename}. Загрузка станет доступна после согласования API.` : "Файл пока не отправляется: нужен контракт загрузки и формат выписки."}</p><EmptyState className="mt-5" title="Источники не подключены" description="Список подключений появится после интеграции с сервером." /></SectionCard>
      )}
    </PageLayout>
  );
}
