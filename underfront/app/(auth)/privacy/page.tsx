import type { Metadata } from "next";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import Link from "next/link";

export const metadata: Metadata = { title: "Обработка персональных данных — ПУЛЬС" };

export default function PrivacyPage() {
  return <main className="flex min-h-screen items-center justify-center bg-[color:var(--sidebar-bg)] px-4 py-12 text-[color:var(--text-primary)]">
    <section className="w-full max-w-[480px] rounded-[6px] border border-[color:var(--border)] bg-[color:var(--auth-card-bg)] p-6 sm:p-8">
      <ContentHeading level={1}>Обработка персональных данных</ContentHeading>
      <ContentText variant="description" className="mt-3">Документ о порядке обработки персональных данных ещё не опубликован в проекте. Его необходимо добавить до публичного запуска регистрации.</ContentText>
      <Link href="/register" className="mt-5 inline-block text-[13px] font-medium text-[color:var(--nav-item-active-text)] underline underline-offset-4">Вернуться к регистрации</Link>
    </section>
  </main>;
}
