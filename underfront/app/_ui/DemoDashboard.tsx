import Link from "next/link";
import { Database } from "lucide-react";
import { PageLayout, SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart, RiskCard } from "@/src/widgets/finance-panels";
import { ContentHeading, ContentText, buttonVariants, EmptyState } from "@/src/shared/ui";
import { MetricTile } from "@/src/widgets/dashboard-metrics";

/** Start screen with honest empty states until the backend contracts are agreed. */
const linkClass = buttonVariants({ variant: "secondary", size: "lg" });

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
        <SectionCard>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div><ContentHeading>Прогноз остатка</ContentHeading><ContentText variant="description" className="mt-1">Факт, базовый и негативный сценарии</ContentText></div>
            <Link href="/forecast" className="text-sm font-semibold text-[color:var(--accent)]">Открыть прогноз →</Link>
          </div>
          <CashflowForecastChart days={[]} />
        </SectionCard>
        <div className="space-y-4">
          <RiskCard risk={null} />
          <EmptyState title="Операций пока нет" description="После подключения источника здесь появятся последние движения денег." action={<Link href="/sources" className={linkClass}><Database size={16} aria-hidden="true" /> Добавить источник</Link>} />
        </div>
      </div>
    </PageLayout>
  );
}
