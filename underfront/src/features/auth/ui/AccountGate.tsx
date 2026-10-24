"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useSession } from "../model/SessionProvider";

export function AccountGate({ children }: { children: ReactNode }) {
  const session = useSession();
  if (session.loading) return <p role="status">Загружаем кабинет…</p>;
  if (session.error) return <p role="alert">{session.error}</p>;
  if (!session.profile) return <Link href="/login">Войти</Link>;
  if (!session.company) return <Link href="/companies/new">Создать компанию</Link>;
  return <>{children}</>;
}
