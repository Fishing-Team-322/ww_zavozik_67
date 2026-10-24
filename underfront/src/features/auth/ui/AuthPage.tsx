"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Checkbox } from "@/src/shared/ui/checkbox";
import { ApiError, clearAccessToken } from "@/src/shared/api/client";
import { useAuth } from "../model/AuthProvider";
import { safeRedirect } from "../model/redirect";
import { authApi } from "../api/auth-api";

type AuthPageProps = { mode: "login" | "register" | "recover" | "reset" };
const inputClass = "h-10 px-4 text-base leading-6";
const passwordClass = "h-10 px-4 pr-12 text-base leading-6";
const buttonClass = "h-10 w-full px-4 text-base leading-6";
const emailValid = (value: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
const passwordValid = (value: string) => value.length >= 8 && new TextEncoder().encode(value).length <= 256;

function messageFor(cause: unknown, mode: AuthPageProps["mode"]) {
  if (cause instanceof ApiError) {
    if (cause.code === "invalid_credentials") return "Неверный email или пароль.";
    if (mode === "register" && cause.status === 409) return "Этот email уже зарегистрирован.";
    if (mode === "reset" && cause.code === "invalid_reset_token") return "Ссылка недействительна или срок её действия истёк. Запросите новую.";
    return cause.message;
  }
  if (cause instanceof TypeError) return "Не удалось подключиться к серверу. Попробуйте позже.";
  return cause instanceof Error ? cause.message : "Не удалось выполнить запрос.";
}

export function AuthPage({ mode }: AuthPageProps) {
  const router = useRouter();
  const { user, status, error: sessionError, sessionExpired, signIn, signUp, retry } = useAuth();
  const submitLock = useRef(false);
  const tokenCaptured = useRef(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [consent, setConsent] = useState(false);
  const [step, setStep] = useState<"email" | "password">("email");
  const [token, setToken] = useState("");
  const [tokenReady, setTokenReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (mode !== "reset" || tokenCaptured.current) return;
    tokenCaptured.current = true;
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "";
    setToken(value);
    setTokenReady(true);
    if (window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, [mode]);

  useEffect(() => {
    if (status !== "authenticated" || (mode !== "login" && mode !== "register")) return;
    const wanted = new URLSearchParams(window.location.search).get("redirect");
    router.replace(user?.companies.length ? safeRedirect(wanted) : "/companies/new");
  }, [status, mode, user, router]);

  async function submitCredentials(action: "login" | "register") {
    if (submitLock.current) return;
    setError("");
    if (!emailValid(email)) { setError("Проверьте адрес электронной почты."); return; }
    if (action === "register") {
      if (!passwordValid(password)) { setError("Пароль должен содержать минимум 8 символов и не более 256 байт."); return; }
      if (password !== confirmation) { setError("Пароли не совпадают."); return; }
      if (!consent) { setError("Необходимо согласие на обработку персональных данных."); return; }
    }
    submitLock.current = true;
    setBusy(true);
    try {
      const profile = action === "login" ? await signIn(email.trim(), password) : await signUp(email.trim(), password);
      const wanted = new URLSearchParams(window.location.search).get("redirect");
      router.replace(profile.companies.length ? safeRedirect(wanted) : "/companies/new");
    } catch (cause) { setError(messageFor(cause, mode)); }
    finally { submitLock.current = false; setBusy(false); }
  }

  async function submitRecovery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current) return;
    if (!emailValid(email)) { setError("Проверьте адрес электронной почты."); return; }
    submitLock.current = true; setBusy(true); setError("");
    try { await authApi.forgotPassword(email.trim()); setSuccess(true); }
    catch (cause) { setError(messageFor(cause, mode)); }
    finally { submitLock.current = false; setBusy(false); }
  }

  async function submitReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current) return;
    if (!token) { setError("В ссылке нет токена. Запросите новую ссылку."); return; }
    if (!passwordValid(password)) { setError("Пароль должен содержать минимум 8 символов и не более 256 байт."); return; }
    if (password !== confirmation) { setError("Пароли не совпадают."); return; }
    submitLock.current = true; setBusy(true); setError("");
    try { await authApi.resetPassword(token, password); clearAccessToken(); setToken(""); setSuccess(true); }
    catch (cause) { setError(messageFor(cause, mode)); }
    finally { submitLock.current = false; setBusy(false); }
  }

  const title = mode === "login" ? "Вход" : mode === "register" ? "Регистрация" : mode === "recover" ? "Восстановление пароля" : "Новый пароль";
  const description = mode === "login" ? "Войдите, чтобы продолжить работу с финансами." : mode === "register" ? step === "email" ? "Начните с адреса электронной почты." : "Придумайте пароль для завершения регистрации." : mode === "recover" ? "Введите email, на который зарегистрирован аккаунт." : "Установите новый пароль для своего аккаунта.";

  return <main className="flex min-h-screen items-center justify-center bg-[color:var(--sidebar-bg)] px-4 py-16 text-[color:var(--text-primary)]" style={{ backgroundImage: "radial-gradient(ellipse 760px 560px at 50% 50%, var(--auth-glow), transparent 78%)" }}>
    <div className="w-full max-w-[420px]">
      <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--auth-card-bg)] p-6 text-[color:var(--nav-item-text)] [--input-label:var(--nav-item-text)] [--input-placeholder:var(--nav-item-text)] [--input-text:var(--nav-item-text)] sm:p-8">
        <h1 className="text-center text-2xl font-semibold tracking-tight text-[color:var(--nav-item-active-text)]">{title}</h1>
        <p className="mt-2 text-center text-sm leading-5">{description}</p>

        {(mode === "login" || mode === "register") && status === "loading" && <p role="status" className="mt-7 text-center text-[13px]">Проверяем сессию…</p>}
        {(mode === "login" || mode === "register") && status === "authenticated" && <p role="status" className="mt-7 text-center text-[13px]">Открываем приложение…</p>}
        {(mode === "login" || mode === "register") && status === "error" && <div className="mt-7 text-center text-[13px]"><p role="alert">{sessionError ?? "Сервер недоступен."}</p><Button type="button" variant="outline" size="lg" className="mt-3" onClick={() => void retry()}>Повторить</Button></div>}

        {mode === "login" && status === "guest" && <form onSubmit={event => { event.preventDefault(); void submitCredentials("login"); }} className="mt-7">
          {sessionExpired && <p role="status" className="mb-4 rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface-subtle)] px-3 py-2 text-[12px]">Срок сессии истёк. Войдите снова.</p>}
          <div className="space-y-4"><Input inputSize="lg" className={inputClass} aria-label="Электронная почта" type="email" placeholder="Электронная почта" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /><Input inputSize="lg" className={passwordClass} aria-label="Пароль" type="password" placeholder="Пароль" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} secretToggle /></div>
          <div className="mt-3 text-right"><Link href="/forgot-password" className="text-xs font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:underline">Забыли пароль?</Link></div>
          {error && <p role="alert" className="mt-3 text-[12px] text-[color:var(--danger)]">{error}</p>}
          <Button type="submit" size="lg" disabled={busy} className={`mt-6 ${buttonClass}`}>{busy ? "Входим…" : "Войти"}</Button>
        </form>}

        {mode === "register" && status === "guest" && step === "email" && <form className="mt-7" onSubmit={event => { event.preventDefault(); if (!emailValid(email)) { setError("Проверьте адрес электронной почты."); return; } setError(""); setStep("password"); }}>
          <Input inputSize="lg" className={inputClass} aria-label="Электронная почта" type="email" placeholder="Электронная почта" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} />
          {error && <p role="alert" className="mt-3 text-[12px] text-[color:var(--danger)]">{error}</p>}
          <Button type="submit" size="lg" className={`mt-6 ${buttonClass}`}>Продолжить</Button>
        </form>}
        {mode === "register" && status === "guest" && step === "password" && <><div className="mt-7 flex items-center justify-between gap-3 rounded-[6px] bg-[color:var(--sidebar-hover)] px-3 py-2 text-xs"><span className="min-w-0 truncate">{email}</span><button type="button" onClick={() => setStep("email")} className="shrink-0 font-medium text-[color:var(--nav-item-active-text)] underline-offset-4 hover:underline focus-visible:underline">Изменить</button></div>
          <form onSubmit={event => { event.preventDefault(); void submitCredentials("register"); }} className="mt-4">
            <div className="space-y-4"><Input inputSize="lg" className={passwordClass} aria-label="Пароль" type="password" minLength={8} required placeholder="Пароль" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} secretToggle /><Input inputSize="lg" className={passwordClass} aria-label="Повторите пароль" type="password" minLength={8} required placeholder="Повторите пароль" autoComplete="new-password" value={confirmation} onChange={event => setConfirmation(event.target.value)} secretToggle /></div>
            <p className="mt-2 text-[12px] leading-4">Минимум 8 символов. Длинная уникальная фраза надёжнее.</p>
            <div className="mt-4"><Checkbox checked={consent} onChange={event => setConsent(event.target.checked)} label="Согласен на обработку персональных данных" /><Link href="/privacy" target="_blank" rel="noopener noreferrer" className="ml-7 block text-[12px] underline underline-offset-4 hover:text-[color:var(--nav-item-active-text)]">Документ об обработке данных</Link><p className="ml-7 mt-1 text-[11px]">Документ необходимо добавить до публичного запуска.</p></div>
            {error && <p role="alert" className="mt-3 text-[12px] text-[color:var(--danger)]">{error}</p>}
            <Button type="submit" size="lg" disabled={busy} className={`mt-6 ${buttonClass}`}>{busy ? "Создаём…" : "Создать аккаунт"}</Button>
          </form></>}

        {mode === "recover" && (success ? <p role="status" className="mt-7 text-center text-[13px] leading-5">Если аккаунт существует, мы отправили письмо с инструкцией.</p> : <form className="mt-7" onSubmit={event => void submitRecovery(event)}><Input inputSize="lg" className={inputClass} aria-label="Электронная почта" type="email" placeholder="Электронная почта" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} />{error && <p role="alert" className="mt-3 text-[12px] text-[color:var(--danger)]">{error}</p>}<Button type="submit" size="lg" disabled={busy} className={`mt-6 ${buttonClass}`}>{busy ? "Отправляем…" : "Восстановить пароль"}</Button></form>)}

        {mode === "reset" && (success ? <div role="status" className="mt-7 text-center text-[13px]"><p>Пароль обновлён. Войдите с новым паролем.</p><Link href="/login" className="mt-4 inline-block font-medium underline underline-offset-4">Перейти ко входу</Link></div> : !tokenReady ? <p role="status" className="mt-7 text-center text-[13px]">Проверяем ссылку…</p> : !token ? <div role="alert" className="mt-7 text-center text-[13px]"><p>В ссылке нет токена. Запросите новую ссылку.</p><Link href="/forgot-password" className="mt-4 inline-block font-medium underline underline-offset-4">Запросить ссылку</Link></div> : <form className="mt-7" onSubmit={event => void submitReset(event)}><div className="space-y-4"><Input inputSize="lg" className={passwordClass} aria-label="Новый пароль" type="password" minLength={8} required placeholder="Новый пароль" autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} secretToggle /><Input inputSize="lg" className={passwordClass} aria-label="Повторите новый пароль" type="password" minLength={8} required placeholder="Повторите новый пароль" autoComplete="new-password" value={confirmation} onChange={event => setConfirmation(event.target.value)} secretToggle /></div><p className="mt-2 text-[12px]">Минимум 8 символов. Используйте уникальный пароль.</p>{error && <p role="alert" className="mt-3 text-[12px] text-[color:var(--danger)]">{error}</p>}<Button type="submit" size="lg" disabled={busy} className={`mt-6 ${buttonClass}`}>{busy ? "Сохраняем…" : "Сохранить новый пароль"}</Button></form>)}

        <p className="mt-7 border-t border-[color:var(--border)] pt-5 text-center text-sm">{mode === "login" ? "Нет аккаунта? " : mode === "register" ? "Уже есть аккаунт? " : "Вспомнили пароль? "}<Link href={mode === "login" ? "/register" : "/login"} className="font-medium underline-offset-4 hover:underline focus-visible:underline">{mode === "login" ? "Зарегистрироваться" : "Войти"}</Link></p>
      </section>
    </div>
  </main>;
}
