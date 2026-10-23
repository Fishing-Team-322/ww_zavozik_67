import type { Metadata } from "next";
import { TestShowcase } from "@/src/components/test/TestShowcase";

export const metadata: Metadata = { title: "Test — ПУЛЬС UI" };

export default function TestPage() {
  return <TestShowcase />;
}
