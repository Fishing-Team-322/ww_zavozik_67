import type { Metadata } from "next";
import { PulsOverviewHome } from "@/src/widgets/puls-overview";

export const metadata: Metadata = { title: "Overview — ПУЛЬС" };

export default function OverviewPage() {
  return <PulsOverviewHome />;
}
