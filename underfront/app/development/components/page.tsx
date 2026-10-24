import type { Metadata } from "next";
import { DevelopmentComponentsShowcase } from "@/app/development/components/_ui/DevelopmentComponentsShowcase";

export const metadata: Metadata = {
  title: "Кнопки и поля — ПУЛЬС UI",
};

export default function DevelopmentComponentsPage() {
  return <DevelopmentComponentsShowcase />;
}
