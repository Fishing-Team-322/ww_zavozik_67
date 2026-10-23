import type { Metadata } from "next";
import { DevelopmentComponentsShowcase } from "@/src/components/development/DevelopmentComponentsShowcase";

export const metadata: Metadata = {
  title: "Кнопки и поля — ПУЛЬС UI",
};

export default function DevelopmentComponentsPage() {
  return <DevelopmentComponentsShowcase />;
}
