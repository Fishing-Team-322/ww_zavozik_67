import Link from "next/link";
import { Database } from "lucide-react";
import { PageLayout } from "@/src/components/cabinet/shared";
import { CashflowForecastChart, RiskCard } from "@/src/components/finance";
import { EmptyState } from "@/src/components/ui";
import { MetricTile } from "@/src/features/cabinet-dashboard/ui";

/** Start screen with honest empty states until the backend contracts are agreed. */
const linkClass = "inline-flex h-10 items-center justify-center gap-2 rounded-[10px] px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]";

export function DemoDashboard() {
  return (
    <PageLayout contentClassName="space-y-6">

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="Текущий остаток" value="—" hint="Ожидает данные" color="var(--accent)" />
        <MetricTile label="Прогноз на 30 дней" value="—" hint="Ожидает расчёт" color="var(--accent)" />
        <MetricTile label="Кассовые разрывы" value="—" hint="Ожидает расчёт" color="var(--danger)" />
        <MetricTile label="Подключённые источники" value="—" hint="Ожидает подключение" color="var(--success)" />
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
        <section className="rounded-[18px] border border-[color:var(--border)] bg-[color:var(--surface)] p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div><h2 className="text-lg font-semibold">Прогноз остатка</h2><p className="mt-1 text-xs text-[color:var(--text-secondary)]">Факт, базовый и негативный сценарии</p></div>
            <Link href="/forecast" className="text-sm font-semibold text-[color:var(--accent)]">Открыть прогноз →</Link>
          </div>
          <CashflowForecastChart days={[]} />
        </section>
        <div className="space-y-4">
          <RiskCard risk={null} />
          <EmptyState title="Операций пока нет" description="После подключения источника здесь появятся последние движения денег." action={<Link href="/sources" className={`${linkClass} border border-[var(--button-secondary-border)] bg-[var(--button-secondary-bg)] text-[var(--button-secondary-fg)] hover:bg-[var(--button-secondary-bg-hover)]`}><Database size={16} aria-hidden="true" /> Добавить источник</Link>} />
        </div>
      </div>
    </PageLayout>
  );
}
