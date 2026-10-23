"use client";

import { type ButtonHTMLAttributes } from "react";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/src/lib/cn";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "outline" | "danger" | "ghost" | "back";
  size?: "sm" | "md" | "lg" | "icon";
  loading?: boolean;
}

const variantClasses: Record<NonNullable<ButtonProps["variant"]>, string> = {
  default: [
    "bg-[image:var(--button-primary-gradient)] text-[var(--button-primary-fg)]",
    "shadow-[var(--button-primary-shadow)]",
    "hover:shadow-[var(--button-primary-shadow-hover)]",
    "active:shadow-[var(--button-primary-shadow-active)]",
  ].join(" "),

  secondary: [
    "border border-[var(--button-secondary-border)]",
    "bg-[var(--button-secondary-bg)] text-[var(--button-secondary-fg)]",
    "hover:bg-[var(--button-secondary-bg-hover)]",
    "active:bg-[var(--button-secondary-bg-active)]",
  ].join(" "),

  outline: [
    "bg-transparent text-[var(--button-outline-fg)]",
    "shadow-[var(--button-outline-shadow)]",
    "hover:bg-[var(--surface-subtle)]",
    "active:bg-[var(--surface-subtle)]",
  ].join(" "),

  danger: [
    "border border-transparent",
    "bg-[var(--button-danger-bg)] text-[var(--button-danger-fg)]",
    "shadow-[var(--button-danger-shadow)]",
    "hover:bg-[var(--button-danger-bg-hover)]",
    "active:bg-[var(--button-danger-bg-active)]",
  ].join(" "),

  ghost: [
    "border border-transparent",
    "bg-transparent text-[var(--button-ghost-fg)]",
    "hover:bg-[var(--button-ghost-bg-hover)]",
    "hover:text-[var(--button-ghost-fg-hover)]",
    "active:bg-[var(--button-ghost-bg-active)]",
  ].join(" "),

  back: [
    "select-none border border-transparent",
    "bg-[color:var(--surface-subtle)] text-[color:var(--text-secondary)]",
    "hover:bg-[color:var(--surface-elevated)] hover:text-[color:var(--text-primary)]",
  ].join(" "),
};

const sizeClasses: Record<NonNullable<ButtonProps["size"]>, string> = {
  sm: "h-5 px-1 py-0.5",
  icon: "h-6 w-6 shrink-0 p-0",
  md: "h-6 px-1.5 py-1",
  lg: "h-8 px-3 py-1.5",
};

/** Общие стили кнопок и их варианты. */
export function buttonVariants({
  variant = "default",
  size = "md",
}: Pick<ButtonProps, "variant" | "size"> = {}) {
  return cn(
    [
      "relative inline-flex cursor-pointer items-center justify-center gap-1 whitespace-nowrap rounded-[6px]",
      "font-medium text-xs leading-4 tabular-nums [&>svg]:size-3",
      "focus-visible:outline-none",
      "focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]",
      "disabled:pointer-events-none disabled:opacity-55",
    ].join(" "),
    variantClasses[variant],
    "transition-[background-color,box-shadow,color] duration-200 ease-[ease] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--focus-ring-offset)]",
    sizeClasses[size]
  );
}

/**
 * Назначение функции: Отображает компонент `Button` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Button({
  className,
  variant = "default",
  size = "md",
  loading = false,
  disabled,
  children,
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        "Загрузка..."
      ) : variant === "back" && children == null ? (
        <ArrowLeft aria-hidden />
      ) : (
        children
      )}
    </button>
  );
}
