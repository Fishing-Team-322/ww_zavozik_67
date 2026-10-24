"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/src/shared/ui/button";
import { useAuth } from "@/src/features/auth/model/AuthProvider";
import { isPublicPath } from "@/src/features/auth/model/redirect";
import { SidebarShell, type SidebarShellProps } from "./SidebarShell";

function SessionState({ message, retry }: { message: string; retry?: () => void }) {
  return <main className="flex min-h-screen items-center justify-center bg-[color:var(--sidebar-bg)] p-6 text-[color:var(--text-primary)]">
    <div className="max-w-sm rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-5 text-center">
      <p role="status" className="text-[13px] text-[color:var(--text-secondary)]">{message}</p>
      {retry && <Button type="button" size="lg" variant="outline" className="mt-4" onClick={retry}>Повторить</Button>}
    </div>
  </main>;
}

/** The API still checks access rights; this gate keeps protected UI out of view during session restoration. */
export function CabinetShell(props: SidebarShellProps) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const { user, status, error, retry } = useAuth();
  const publicRoute = isPublicPath(pathname);
  const adminRoute = pathname === "/admin" || pathname.startsWith("/admin/");
  const needsOnboarding = !adminRoute && status === "authenticated" && user?.companies.length === 0 && pathname !== "/companies/new";

  useEffect(() => {
    if (publicRoute) return;
    if (status === "guest") {
      const target = window.location.pathname + window.location.search;
      router.replace(`/login?redirect=${encodeURIComponent(target)}`);
    } else if (needsOnboarding) router.replace("/companies/new");
  }, [publicRoute, status, needsOnboarding, router]);

  if (publicRoute) return <>{props.children}</>;
  if (status === "loading") return <SessionState message="Восстанавливаем сессию…" />;
  if (status === "error") return <SessionState message={error ?? "Не удалось подключиться к серверу."} retry={() => void retry()} />;
  if (status === "guest" || needsOnboarding) return <SessionState message="Открываем нужную страницу…" />;
  if (pathname.startsWith("/admin/") || pathname === "/admin") {
    if (user?.role !== "admin") return <SessionState message="403 · У вас нет доступа к разделу администратора." />;
    return <>{props.children}</>;
  }
  return <SidebarShell {...props} userName={user?.email ?? props.userName} />;
}
