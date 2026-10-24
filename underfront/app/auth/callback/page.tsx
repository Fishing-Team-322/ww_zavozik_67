"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth, useSession } from "@/src/features/auth";

import { api } from "@/src/shared/api";

export default function OAuthCallbackPage() {
  const session = useSession();
  const router = useRouter();
  const { retry } = useAuth();
  const started = useRef(false);
  const [completed, setCompleted] = useState(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api.allowSessionRestore();
    void retry().then(() => setCompleted(true));
  }, [retry]);
  useEffect(() => {
    if (completed && session.profile) router.replace(session.profile.role === "admin" ? "/admin" : session.profile.companies.length ? "/overview" : "/companies/new");
  }, [completed, session.profile, router]);
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="space-y-4">
        <p role="status">
          {!completed || session.loading || session.profile
            ? "Завершаем вход…"
            : session.error || "Не удалось завершить вход. Попробуйте ещё раз."}
        </p>
        {completed && !session.loading && !session.profile && (
          <Link className="text-[color:var(--accent)]" href="/login">
            Вернуться ко входу
          </Link>
        )}
      </div>
    </main>
  );
}
