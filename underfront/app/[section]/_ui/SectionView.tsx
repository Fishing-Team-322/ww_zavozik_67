"use client";

import { AccountGate, useSession } from "@/src/features/auth";
import { PageLayout } from "@/src/widgets/cabinet-shell";
import type { Section } from "@/src/entities/navigation";
import { TransactionsScreen } from "./TransactionsScreen";
import { ForecastScreen } from "./ForecastScreen";
import { ScenariosScreen } from "./ScenariosScreen";
import { CalendarScreen } from "./CalendarScreen";
import { SourcesScreen } from "./SourcesScreen";
import { RisksScreen } from "./RisksScreen";

const screens = {
  transactions: TransactionsScreen,
  forecast: ForecastScreen,
  scenarios: ScenariosScreen,
  calendar: CalendarScreen,
  sources: SourcesScreen,
  risks: RisksScreen,
};
export function SectionView({ section }: { section: Section }) {
  const { company } = useSession();
  const Screen = screens[section];
  return (
    <PageLayout>
      <AccountGate>
        <Screen key={`${section}:${company?.id}`} />
      </AccountGate>
    </PageLayout>
  );
}
