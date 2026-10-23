"use client";

import { Button, ErrorState } from "@/src/components/ui";
import { PageLayout } from "@/src/components/cabinet/shared";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <PageLayout>
        <div className="max-w-2xl">
          <ErrorState title="Попробуйте ещё раз" description="Если ошибка повторится, вернитесь к обзору и откройте раздел заново." action={<Button onClick={reset}>Повторить</Button>} />
        </div>
    </PageLayout>
  );
}
