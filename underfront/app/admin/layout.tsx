"use client";
import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/src/features/auth/model/AuthProvider";
import { Button } from "@/src/shared/ui";

const links = [["/admin", "Обзор"], ["/admin/users", "Пользователи"], ["/admin/companies", "Компании"], ["/admin/integrations", "Интеграции"], ["/admin/models", "Модели"], ["/admin/classifier", "Классификатор"], ["/admin/antifraud/signals", "Антифрод"], ["/admin/audit", "Журнал доступа"]];
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth(); const path = usePathname();
  const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  return <div className="min-h-screen bg-[color:var(--surface)] text-[color:var(--text-primary)]"><header className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--border)] p-4"><h1 className="font-semibold">ПУЛЬС · Администрирование</h1><div className="flex items-center gap-4"><span className="text-sm">{user?.email}</span>{!!user?.companies.length && <Link className="underline" href="/overview">Моя компания</Link>}<Button variant="outline" onClick={() => { const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", next); try { localStorage.setItem("puls-theme", next); } catch {} }}>Сменить тему</Button><Button variant="ghost" loading={busy} onClick={async () => { setBusy(true); setError(null); try { await signOut(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось выйти"); } finally { setBusy(false); } }}>Выйти</Button></div></header>{error && <p role="alert" className="p-4">{error}</p>}<div className="grid gap-5 p-4 md:grid-cols-[200px_minmax(0,1fr)]"><nav aria-label="Разделы администратора" className="flex gap-2 overflow-x-auto md:flex-col">{links.map(([href, label]) => <Link key={href} href={href} aria-current={path === href ? "page" : undefined} className={`whitespace-nowrap rounded-md p-2 text-sm ${path === href ? "bg-[color:var(--accent-soft)] text-[color:var(--accent)]" : "hover:bg-[color:var(--surface-subtle)]"}`}>{label}</Link>)}</nav><main className="min-w-0">{children}</main></div></div>;
}
