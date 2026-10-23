import Link from "next/link";
import { EmptyState } from "@/src/components/ui";
import { PageLayout } from "@/src/components/cabinet/shared";

export default function NotFound() {
  return (
    <PageLayout>
        <div className="max-w-2xl">
          <EmptyState title="Такой страницы нет" action={<Link href="/" className="font-semibold text-[color:var(--accent)]">Вернуться к обзору</Link>} />
        </div>
    </PageLayout>
  );
}
