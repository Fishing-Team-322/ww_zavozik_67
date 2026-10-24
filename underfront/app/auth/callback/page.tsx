"use client";
import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "@/src/features/auth";

export default function OAuthCallbackPage() {
  const session = useSession();
  const router = useRouter();
  useEffect(() => {
    if (session.profile) router.replace("/");
  }, [session.profile, router]);
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="space-y-4">
        <p role="status">
          {session.loading || session.profile
            ? "Завершаем вход…"
            : session.error || "Не удалось завершить вход. Попробуйте ещё раз."}
        </p>
        {!session.loading && !session.profile && (
          <Link className="text-[color:var(--accent)]" href="/login">
            Вернуться ко входу
          </Link>
        )}
      </div>
    </main>
  );
}
