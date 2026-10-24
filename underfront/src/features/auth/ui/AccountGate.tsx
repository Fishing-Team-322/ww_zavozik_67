"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";
import { message } from "@/src/shared/api";
import { useSession } from "../model/SessionProvider";

export function AccountGate({ children }: { children: ReactNode }) {
  const session = useSession();
  const [name, setName] = useState("");
  const [legal, setLegal] = useState("ООО");
  const [industry, setIndustry] = useState("services");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (session.loading)
    return (
      <p
        role="status"
        className="p-5 text-sm text-[color:var(--text-secondary)]"
      >
        Загружаем кабинет…
      </p>
    );
  if (session.error)
    return (
      <div className="space-y-4 p-5">
        <p role="alert">{session.error}</p>
        <Button onClick={() => window.location.reload()}>Повторить</Button>
      </div>
    );
  if (!session.profile)
    return (
      <div className="space-y-4 rounded-xl border border-[color:var(--border)] p-6">
        <h1 className="text-xl font-semibold">Финансы вашего бизнеса</h1>
        <p className="text-sm text-[color:var(--text-secondary)]">
          Войдите или создайте аккаунт, чтобы загрузить выписку и получить
          прогноз.
        </p>
        <div className="flex gap-5">
          <Link
            className="font-semibold text-[color:var(--accent)]"
            href="/login"
          >
            Войти
          </Link>
          <Link
            className="font-semibold text-[color:var(--accent)]"
            href="/register"
          >
            Создать аккаунт
          </Link>
        </div>
      </div>
    );
  if (!session.company)
    return (
      <form
        className="max-w-lg space-y-4 rounded-xl border border-[color:var(--border)] p-6"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await session.createCompany({
              name,
              legal_form: legal as "ООО" | "ИП",
              industry,
            });
          } catch (error) {
            setError(message(error));
          } finally {
            setBusy(false);
          }
        }}
      >
        <h1 className="text-xl font-semibold">Добавьте компанию</h1>
        <p className="text-sm text-[color:var(--text-secondary)]">
          Её операции и планы будут доступны только вам.
        </p>
        <Input
          label="Название компании"
          required
          maxLength={300}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Select
          label="Форма бизнеса"
          value={legal}
          onChange={(event) => setLegal(event.target.value)}
          options={[
            { value: "ООО", label: "ООО" },
            { value: "ИП", label: "ИП" },
          ]}
        />
        <Select
          label="Отрасль"
          value={industry}
          onChange={(event) => setIndustry(event.target.value)}
          options={[
            { value: "services", label: "Услуги" },
            { value: "retail", label: "Торговля" },
            { value: "manufacturing", label: "Производство" },
            { value: "other", label: "Другое" },
          ]}
        />
        {error && (
          <p role="alert" className="text-sm text-[color:var(--danger)]">
            {error}
          </p>
        )}
        <Button type="submit" size="lg" loading={busy}>
          Создать компанию
        </Button>
      </form>
    );
  return <>{children}</>;
}
