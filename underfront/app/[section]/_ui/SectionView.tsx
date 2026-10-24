"use client";

import { useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { PageLayout, SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart, RiskCard } from "@/src/widgets/finance-panels";
import { PaymentCalendarDemo } from "@/src/features/payment-calendar";
import { ForecastChart, PULS_DEMO_DATA, ScenarioComparison, type ScenarioKey } from "@/src/widgets/puls-overview/ui/PulsOverview";
import { EmptyState, Input } from "@/src/shared/ui";
import type { Section } from "@/src/entities/navigation";

export function SectionView({ section }: { section: Section }) {
  const [query, setQuery] = useState("");
  const [scenario, setScenario] = useState<ScenarioKey>("base");
  const [horizon, setHorizon] = useState<30 | 60 | 90>(30);
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
        <div className="puls-overview min-w-0 bg-[color:var(--puls-bg)] pb-6 text-[color:var(--puls-text)]">
          <p className="text-[12px] text-[color:var(--puls-text-muted)]">Синтетические демо-данные · выберите сценарий в графике или таблице</p>
          <ForecastChart data={PULS_DEMO_DATA} selected={scenario} horizon={horizon} onChangeHorizon={setHorizon} onChangeScenario={setScenario} />
          <ScenarioComparison data={PULS_DEMO_DATA} selected={scenario} onChangeScenario={setScenario} />
        </div>
      )}

      {section === "risks" && (
        <div className="grid gap-4 lg:grid-cols-2"><RiskCard risk={null} /><EmptyState title="Периоды дефицита неизвестны" description="Загрузите данные и получите прогноз, чтобы увидеть даты, суммы и причины разрывов." /></div>
      )}

      {section === "calendar" && (
        <PaymentCalendarDemo />
      )}


    </PageLayout>
  );
}
