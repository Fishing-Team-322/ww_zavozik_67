import type { Metadata } from "next";
import { NewCompanyForm } from "@/src/features/company-create/NewCompanyForm";

export const metadata: Metadata = { title: "Новая компания — ПУЛЬС" };

export default function NewCompanyPage() {
  return <NewCompanyForm />;
}
