import type { Metadata } from "next";
import { SourcesWorkspace } from "@/src/features/sources/SourcesWorkspace";

export const metadata: Metadata = { title: "Источники данных — ПУЛЬС" };

export default function SourcesPage() {
  return <SourcesWorkspace />;
}
