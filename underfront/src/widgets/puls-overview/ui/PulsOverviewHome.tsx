"use client";

import { useRouter } from "next/navigation";
import PulsOverview, { PULS_DEMO_DATA } from "./PulsOverview";

export function PulsOverviewHome() {
  const router = useRouter();

  return (
    <PulsOverview
      data={PULS_DEMO_DATA}
      onAddSource={() => router.push("/sources")}
      onOpenForecast={() => router.push("/forecast")}
      onOpenCalendar={() => router.push("/calendar")}
      onOpenScenarios={() => router.push("/scenarios")}
    />
  );
}
