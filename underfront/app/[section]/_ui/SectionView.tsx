"use client";

import { AccountGate, useSession } from "@/src/features/auth";
import { PageLayout } from "@/src/widgets/cabinet-shell";
import type { Section } from "@/src/entities/navigation";
import { TransactionsScreen } from "./TransactionsScreen";
import { ForecastScreen } from "./ForecastScreen";
import { ScenariosScreen } from "./ScenariosScreen";
import { CalendarScreen } from "./CalendarScreen";
import { RecurringScreen } from "./RecurringScreen";
import { DocumentsScreen } from "./DocumentsScreen";
import { PlanFactScreen } from "./PlanFactScreen";
import { CounterpartiesScreen } from "./CounterpartiesScreen";
import { NotificationsScreen } from "@/src/features/notifications";
import { SettingsScreen } from "./SettingsScreen";
import { MethodologyScreen } from "./MethodologyScreen";
import { RisksScreen } from "./RisksScreen";

const screens = {
  transactions: TransactionsScreen,
  forecast: ForecastScreen,
  scenarios: ScenariosScreen,
  calendar: CalendarScreen,
  recurring: RecurringScreen,
  documents: DocumentsScreen,
  "plan-fact": PlanFactScreen,
  counterparties: CounterpartiesScreen,
  notifications: NotificationsScreen,
  settings: SettingsScreen,
  methodology: MethodologyScreen,
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
