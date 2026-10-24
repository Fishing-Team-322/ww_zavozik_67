"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { api, message, type Schemas } from "@/src/shared/api";
import { useSession } from "../model/SessionProvider";

const field = "h-10 px-4 text-base leading-6";
const passwordField = "h-10 px-4 pr-12 text-base leading-6";
const action = "h-10 w-full px-4 text-base leading-6";

export function AuthPage({
  mode,
}: {
  mode: "login" | "register" | "recover" | "reset";
}) {
  const session = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [consent, setConsent] = useState(false);
  const [step, setStep] = useState<"email" | "password">("email");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [resetToken, setResetToken] = useState("");
  const [providers, setProviders] = useState<Schemas["AuthProviders"]>([]);
  useEffect(() => {
    if (mode !== "login" && mode !== "register") return;
    const controller = new AbortController();
    api
      .request<Schemas["AuthProviders"]>("/v1/auth/providers", {
        authenticated: false,
        signal: controller.signal,
      })
      .then(setProviders)
      .catch(() => {});
    return () => controller.abort();
  }, [mode]);
  useEffect(() => {
    if (mode !== "reset") return;
    const token =
      new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    const timer = setTimeout(() => {
      setResetToken(token);
      window.history.replaceState(null, "", window.location.pathname);
    }, 0);
    return () => clearTimeout(timer);
  }, [mode]);
  useEffect(() => {
    if (session.profile && (mode === "login" || mode === "register"))
      router.replace("/");
  }, [session.profile, mode, router]);
  const title = {
    login: "Вход",
    register: "Регистрация",
    recover: "Восстановление пароля",
    reset: "Новый пароль",
  }[mode];
  const description =
    mode === "login"
      ? "Войдите, чтобы продолжить работу с финансами."
      : mode === "recover"
        ? "Введите email, на который зарегистрирован аккаунт."
        : mode === "reset"
          ? "Задайте новый пароль для аккаунта."
          : step === "email"
            ? "Начните с адреса электронной почты."
            : "Придумайте пароль для завершения регистрации.";
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (mode === "register" && step === "email") {
      setStep("password");
      return;
    }
    if ((mode === "register" || mode === "reset") && password !== repeat) {
      setError("Пароли не совпадают.");
      return;
    }
    if (mode === "reset" && !resetToken) {
      setError("В ссылке нет токена восстановления. Запросите новое письмо.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "recover") {
        await api.request<void>("/v1/auth/password/forgot", {
          method: "POST",
          authenticated: false,
          json: { email },
        });
        setDone(true);
      } else if (mode === "reset") {
        await api.request<void>("/v1/auth/password/reset", {
          method: "POST",
          authenticated: false,
          json: { token: resetToken, new_password: password },
        });
        setResetToken("");
        setPassword("");
        setRepeat("");
        setDone(true);
      } else {
        await session.login(mode, email, password, consent);
        router.replace("/");
      }
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main
      className="flex min-h-screen items-center justify-center bg-[color:var(--sidebar-bg)] px-4 py-12 text-[color:var(--text-primary)]"
      style={{
        backgroundImage:
          "radial-gradient(ellipse 760px 560px at 50% 50%, var(--auth-glow), transparent 78%)",
      }}
    >
      <div className="w-full max-w-[420px]">
        <section className="rounded-[12px] border border-[color:var(--border)] bg-[color:var(--auth-card-bg)] p-6 text-[color:var(--nav-item-text)] shadow-[var(--shadow-sm)] [--input-label:var(--nav-item-text)] [--input-placeholder:var(--nav-item-text)] [--input-text:var(--nav-item-text)] sm:p-8">
          <h1 className="text-center text-2xl font-semibold tracking-tight text-[color:var(--nav-item-active-text)]">
            {title}
          </h1>
          <p className="mt-2 text-center text-sm leading-5">{description}</p>
          {done ? (
            <p role="status" className="mt-7 text-sm leading-6">
              {mode === "reset"
                ? "Пароль изменён. Теперь можно войти."
                : "Если аккаунт существует, письмо со ссылкой восстановления будет отправлено на указанный адрес."}
            </p>
          ) : (
            <form className="mt-7 space-y-4" onSubmit={submit}>
              {(mode === "login" ||
                mode === "recover" ||
                (mode === "register" && step === "email")) && (
                <Input
                  inputSize="lg"
                  className={field}
                  aria-label="Электронная почта"
                  type="email"
                  placeholder="Электронная почта"
                  autoComplete="email"
                  required
                  value={email}
                  disabled={busy}
                  onChange={(event) => setEmail(event.target.value)}
                />
              )}
              {mode === "register" && step === "password" && (
                <div className="flex items-center justify-between gap-3 rounded-[6px] bg-[color:var(--sidebar-hover)] px-3 py-2 text-xs">
                  <span className="truncate">{email}</span>
                  <button
                    type="button"
                    disabled={busy}
                    className="font-medium hover:underline"
                    onClick={() => setStep("email")}
                  >
                    Изменить
                  </button>
                </div>
              )}
              {(mode === "login" ||
                mode === "reset" ||
                (mode === "register" && step === "password")) && (
                <Input
                  inputSize="lg"
                  className={passwordField}
                  aria-label="Пароль"
                  type="password"
                  placeholder="Пароль"
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  required
                  minLength={mode === "login" ? 1 : 8}
                  maxLength={256}
                  value={password}
                  disabled={busy}
                  secretToggle
                  onChange={(event) => setPassword(event.target.value)}
                />
              )}
              {(mode === "reset" ||
                (mode === "register" && step === "password")) && (
                <Input
                  inputSize="lg"
                  className={passwordField}
                  aria-label="Повторите пароль"
                  type="password"
                  placeholder="Повторите пароль"
                  autoComplete="new-password"
                  required
                  minLength={8}
                  maxLength={256}
                  value={repeat}
                  disabled={busy}
                  secretToggle
                  onChange={(event) => setRepeat(event.target.value)}
                />
              )}
              {mode === "register" && step === "password" && (
                <label className="flex items-start gap-2 text-xs leading-5">
                  <input
                    type="checkbox"
                    required
                    checked={consent}
                    disabled={busy}
                    onChange={(event) => setConsent(event.target.checked)}
                  />
                  Согласен на обработку персональных данных
                </label>
              )}
              {mode === "login" && (
                <div className="text-right">
                  <Link
                    href="/forgot-password"
                    className="text-xs font-medium hover:underline"
                  >
                    Забыли пароль?
                  </Link>
                </div>
              )}
              {error && (
                <p role="alert" className="text-sm text-[color:var(--danger)]">
                  {error}
                </p>
              )}
              <Button type="submit" size="lg" className={action} loading={busy}>
                {mode === "login"
                  ? "Войти"
                  : mode === "recover"
                    ? "Восстановить пароль"
                    : mode === "reset"
                      ? "Сохранить пароль"
                      : step === "email"
                        ? "Продолжить"
                        : "Создать аккаунт"}
              </Button>
            </form>
          )}
          {providers.length > 0 && (
            <div className="mt-5 space-y-2">
              {providers.map((provider) => (
                <a
                  key={provider}
                  className="block rounded-md border border-[color:var(--border)] px-4 py-2 text-center text-sm hover:bg-[color:var(--sidebar-hover)]"
                  href={`${api.origin}/v1/auth/oauth/${provider}/start`}
                >
                  Войти через {provider === "google" ? "Google" : "Яндекс"}
                </a>
              ))}
            </div>
          )}
          <p className="mt-7 border-t border-[color:var(--border)] pt-5 text-center text-sm">
            {mode === "login"
              ? "Нет аккаунта? "
              : mode === "register"
                ? "Уже есть аккаунт? "
                : "Вернуться ко входу: "}
            <Link
              href={mode === "login" ? "/register" : "/login"}
              className="font-medium hover:underline"
            >
              {mode === "login" ? "Зарегистрироваться" : "Войти"}
            </Link>
          </p>
        </section>
      </div>
    </main>
  );
}
