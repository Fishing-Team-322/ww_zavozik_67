"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";

type AuthPageProps = {
  mode: "login" | "register" | "recover";
};

const authInputClassName = "h-10 px-4 text-base leading-6";
const authPasswordClassName = "h-10 px-4 pr-12 text-base leading-6";
const authButtonClassName = "h-10 w-full px-4 text-base leading-6";

export function AuthPage({ mode }: AuthPageProps) {
  const [email, setEmail] = useState("");
  const [registerStep, setRegisterStep] = useState<"email" | "password">("email");
  const [recoverySubmitted, setRecoverySubmitted] = useState(false);

  const title = mode === "login" ? "Вход" : mode === "register" ? "Регистрация" : "Восстановление пароля";
  const description = mode === "login"
    ? "Войдите, чтобы продолжить работу с финансами."
    : mode === "recover"
      ? "Введите email, на который зарегистрирован аккаунт."
      : registerStep === "email"
        ? "Начните с адреса электронной почты."
        : "Придумайте пароль для завершения регистрации.";

  return (
    <main
      className="flex min-h-screen items-center justify-center bg-[color:var(--sidebar-bg)] px-4 py-12 text-[color:var(--text-primary)]"
      style={{ backgroundImage: "radial-gradient(ellipse 760px 560px at 50% 50%, var(--auth-glow), transparent 78%)" }}
    >
      <div className="w-full max-w-[420px]">
        <section className="rounded-[12px] border border-[color:var(--border)] bg-[color:var(--auth-card-bg)] p-6 text-[color:var(--nav-item-text)] shadow-[var(--shadow-sm)] [--input-label:var(--nav-item-text)] [--input-placeholder:var(--nav-item-text)] [--input-text:var(--nav-item-text)] sm:p-8">
          <h1 className="text-center text-2xl font-semibold tracking-tight text-[color:var(--nav-item-active-text)]">
            {title}
          </h1>
          <p className="mt-2 text-center text-sm leading-5">{description}</p>

          {mode === "login" ? (
            <>
              <div className="mt-7 space-y-4">
                <Input inputSize="lg" className={authInputClassName} aria-label="Электронная почта" type="email" placeholder="Электронная почта" autoComplete="email" />
                <Input inputSize="lg" className={authPasswordClassName} aria-label="Пароль" type="password" placeholder="Пароль" autoComplete="current-password" secretToggle />
              </div>
              <div className="mt-3 text-right">
                <Link href="/forgot-password" className="text-xs font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:underline">
                  Забыли пароль?
                </Link>
              </div>
              <Button type="button" size="lg" className={`mt-6 ${authButtonClassName}`}>Войти</Button>
              <p className="mt-3 text-center text-xs leading-4">Авторизация пока не подключена</p>
            </>
          ) : null}

          {mode === "register" && registerStep === "email" ? (
            <form
              className="mt-7"
              onSubmit={(event) => {
                event.preventDefault();
                setRegisterStep("password");
              }}
            >
              <Input
                inputSize="lg"
                className={authInputClassName}
                aria-label="Электронная почта"
                type="email"
                placeholder="Электронная почта"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
              <Button type="submit" size="lg" className={`mt-6 ${authButtonClassName}`}>Продолжить</Button>
            </form>
          ) : null}

          {mode === "register" && registerStep === "password" ? (
            <>
              <div className="mt-7 flex items-center justify-between gap-3 rounded-[6px] bg-[color:var(--sidebar-hover)] px-3 py-2 text-xs">
                <span className="min-w-0 truncate">{email}</span>
                <button type="button" onClick={() => setRegisterStep("email")} className="shrink-0 font-medium text-[color:var(--nav-item-active-text)] underline-offset-4 hover:underline focus-visible:outline-none focus-visible:underline">
                  Изменить
                </button>
              </div>
              <div className="mt-4 space-y-4">
                <Input inputSize="lg" className={authPasswordClassName} aria-label="Пароль" type="password" placeholder="Пароль" autoComplete="new-password" secretToggle />
                <Input inputSize="lg" className={authPasswordClassName} aria-label="Повторите пароль" type="password" placeholder="Повторите пароль" autoComplete="new-password" secretToggle />
              </div>
              <Button type="button" size="lg" className={`mt-6 ${authButtonClassName}`}>Создать аккаунт</Button>
              <p className="mt-3 text-center text-xs leading-4">Регистрация пока не подключена</p>
            </>
          ) : null}

          {mode === "recover" ? (
            <form
              className="mt-7"
              onSubmit={(event) => {
                event.preventDefault();
                setRecoverySubmitted(true);
              }}
            >
              <Input
                inputSize="lg"
                className={authInputClassName}
                aria-label="Электронная почта"
                type="email"
                placeholder="Электронная почта"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setRecoverySubmitted(false);
                }}
              />
              <Button type="submit" size="lg" className={`mt-6 ${authButtonClassName}`}>Восстановить пароль</Button>
              <p className="mt-3 text-center text-xs leading-4">
                {recoverySubmitted ? "Это демо: письмо не отправлено" : "Восстановление пока не подключено"}
              </p>
            </form>
          ) : null}

          <p className="mt-7 border-t border-[color:var(--border)] pt-5 text-center text-sm">
            {mode === "login" ? "Нет аккаунта? " : mode === "register" ? "Уже есть аккаунт? " : "Вспомнили пароль? "}
            <Link href={mode === "login" ? "/register" : "/login"} className="font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:underline">
              {mode === "login" ? "Зарегистрироваться" : "Войти"}
            </Link>
          </p>
        </section>
      </div>
    </main>
  );
}
