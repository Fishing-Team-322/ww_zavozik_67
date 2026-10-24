"use client";

import { ReactNode, useContext } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Button } from "@/src/shared/ui/button";
import { cn } from "@/src/shared/lib/cn";
import { PageHeaderSlotContext } from "./PageHeaderSlot";

export type PageHeaderBackButton =
  | boolean
  | {
      href?: string;
      ariaLabel?: string;
    };

export type PageHeaderVariant =
  | "plain"
  | "compact"
  | "listing"
  | "hero"
  | "detail";

export type PageHeaderProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  headingLevel?: 1 | 2;
  backButton?: PageHeaderBackButton;
  variant?: PageHeaderVariant;
  badge?: ReactNode;
  meta?: ReactNode;
  leading?: ReactNode;
};

const variantClasses: Record<PageHeaderVariant, string> = {
  plain: "px-0 py-0",
  compact: "px-0 py-0",
  listing: "px-0 py-0",
  detail: "px-0 py-0",
  hero: "relative overflow-hidden rounded-[28px] border border-[color:var(--border)] bg-[image:var(--hero-gradient)] px-5 py-7 shadow-[var(--shadow-sm)] sm:px-7 sm:py-8",
};

/**
 * Назначение функции: Показывает заголовок, описание и действия страницы, перенося действия при нехватке ширины.
 * Зачем используется: Сохраняет единое оформление и читаемый заголовок на широком и узком экране.
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
  titleClassName,
  descriptionClassName,
  headingLevel = 1,
  backButton,
  variant = "plain",
  badge,
  meta,
  leading,
}: PageHeaderProps) {
  const router = useRouter();
  const headerSlot = useContext(PageHeaderSlotContext);

  const showBackButton = Boolean(backButton);
  const HeadingTag = headingLevel === 2 ? "h2" : "h1";
  const showMetaRow = Boolean(badge) || Boolean(meta);
  const backHref = typeof backButton === "object" ? backButton.href : undefined;
  const backAriaLabel =
    typeof backButton === "object" && backButton.ariaLabel
      ? backButton.ariaLabel
      : "Вернуться назад";

  /**
   * Назначение функции: Обрабатывает данные объекта «страница»; операция `handleBackClick`.
   * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
   */
  const handleBackClick = () => {
    if (backHref) {
      router.push(backHref);
      return;
    }

    router.back();
  };

  const header = (
    <header className={cn(variantClasses[variant], className)}>
      <div className="flex w-full flex-wrap items-start justify-between gap-5">
        <div className="flex min-w-0 flex-1 basis-full items-start gap-3 sm:basis-80">
          {showBackButton ? (
            <Button
              type="button"
              variant="back"
              onClick={handleBackClick}
              aria-label={backAriaLabel}
              className="shrink-0"
            />
          ) : null}

          {leading ? <div className="shrink-0">{leading}</div> : null}
          <div className="min-w-0 flex-1">
            {showMetaRow ? (
              <div className="mb-2 flex flex-wrap items-center gap-3">
                {badge ? <div>{badge}</div> : null}
                {meta ? <div>{meta}</div> : null}
              </div>
            ) : null}

            <HeadingTag
              className={cn(
                "max-w-4xl text-[38px] font-semibold leading-tight text-[color:var(--text-primary)]",
                titleClassName
              )}
            >
              {title}
            </HeadingTag>

            {description ? (
              <p
                className={cn(
                  "mt-2 max-w-3xl text-[16px] leading-6 text-[color:var(--text-secondary)]",
                  descriptionClassName
                )}
              >
                {description}
              </p>
            ) : null}
          </div>
        </div>

        {actions ? (
          <div className="flex w-full max-w-full flex-wrap items-center justify-start gap-2 sm:w-auto sm:justify-end">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  );

  return headerSlot ? createPortal(header, headerSlot) : header;
}
