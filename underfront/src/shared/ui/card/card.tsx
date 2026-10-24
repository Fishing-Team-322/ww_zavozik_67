import {
  cloneElement,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import { Button, type ButtonProps } from "@/src/shared/ui/button";
import { contentTypography } from "../content";
import { cn } from "@/src/shared/lib/cn";

export type CardVariant = "default" | "text" | "kpi" | "content";

export interface CardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  variant?: CardVariant;
  title?: ReactNode;
  action?: ReactElement<ButtonProps, typeof Button>;
  contentClassName?: string;
}

const variantClasses: Record<CardVariant, string> = {
  content: "min-w-0 rounded-md border border-[color:var(--border)] bg-[color:var(--card-bg)] p-4 text-[13px] leading-5 shadow-none",
  default: "bg-[color:var(--card-bg)]",
  text: "bg-[color:var(--surface-subtle)] p-5",
  kpi: "bg-[color:var(--border)] p-5",
};

/**
 * Назначение функции: Отображает компонент `Card` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Card({
  className,
  variant = "default",
  title,
  action,
  contentClassName,
  children,
  ...props
}: CardProps) {
  const hasHeader = title != null || action != null;

  return (
    <div
      className={cn(
        "text-[color:var(--card-foreground)]",
        variant !== "content" && "rounded-[18px] border-0",
        variantClasses[variant],
        className
      )}
      {...props}
      data-slot="card"
    >
      {hasHeader ? (
        <>
          <div className="flex items-start justify-between gap-4">
            {title != null ? (
              <h3 className={cn("min-w-0", contentTypography.section)}>
                {title}
              </h3>
            ) : (
              <span />
            )}
            {action ? cloneElement(action, { size: "sm" }) : null}
          </div>
          {children != null ? (
            <div className={cn("mt-4", contentClassName)}>{children}</div>
          ) : null}
        </>
      ) : (
        children
      )}
    </div>
  );
}

export interface LayeredCardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title: ReactNode;
  action?: ReactElement<ButtonProps, typeof Button>;
  top?: ReactNode;
  middle: ReactNode;
  bottom: ReactNode;
}

/**
 * Назначение функции: Собирает трёхслойную карточку из текстового верха, контрастной середины и текстового низа.
 * Зачем используется: Даёт готовую композицию с единым заголовком и произвольным содержимым каждого слоя.
 */
export function LayeredCard({
  title,
  action,
  top,
  middle,
  bottom,
  className,
  ...props
}: LayeredCardProps) {
  return (
    <div
      className={cn(
        "grid gap-px overflow-hidden rounded-[18px] bg-[color:var(--surface)]",
        className
      )}
      {...props}
    >
      <Card
        variant="text"
        title={title}
        action={action}
        className="rounded-b-none"
      >
        {top}
      </Card>
      <Card variant="kpi" className="rounded-none">
        {middle}
      </Card>
      <Card variant="text" className="rounded-t-none">
        {bottom}
      </Card>
    </div>
  );
}

export interface SplitCardProps
  extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  left: ReactNode;
  right: ReactNode;
  leftTitle?: ReactNode;
  rightTitle?: ReactNode;
  leftAction?: ReactElement<ButtonProps, typeof Button>;
  rightAction?: ReactElement<ButtonProps, typeof Button>;
}

/**
 * Назначение функции: Объединяет две равные текстовые секции в одну карточку с разделителем цвета KPI-композиции.
 * Зачем используется: Связанные данные можно сопоставить рядом без двух отдельных внешних карточек и лишних рамок.
 */
export function SplitCard({
  left,
  right,
  leftTitle,
  rightTitle,
  leftAction,
  rightAction,
  className,
  ...props
}: SplitCardProps) {
  return (
    <div
      className={cn(
        "grid gap-px overflow-hidden rounded-[18px] bg-[color:var(--surface)] md:grid-cols-2",
        className
      )}
      {...props}
      data-slot="split-card"
    >
      <Card
        variant="text"
        title={leftTitle}
        action={leftAction}
        className="min-w-0 rounded-none"
      >
        {left}
      </Card>
      <Card
        variant="text"
        title={rightTitle}
        action={rightAction}
        className="min-w-0 rounded-none"
      >
        {right}
      </Card>
    </div>
  );
}

export interface KpiCardProps
  extends Omit<CardProps, "action" | "children" | "title" | "variant"> {
  label: ReactNode;
  value: ReactNode;
  caption?: ReactNode;
}

/**
 * Назначение функции: Показывает одно KPI-значение на контрастной поверхности без рамки.
 * Зачем используется: Сохраняет единый порядок подписи, значения и пояснения в аналитических блоках.
 */
export function KpiCard({
  label,
  value,
  caption,
  className,
  ...props
}: KpiCardProps) {
  return (
    <Card
      variant="kpi"
      className={cn("min-h-32", className)}
      {...props}
    >
      <p className={contentTypography.description}>
        {label}
      </p>
      <p className={cn("mt-3 text-[color:var(--text-primary)]", contentTypography.kpi)}>
        {value}
      </p>
      {caption != null ? (
        <p className={cn("mt-3", contentTypography.description)}>
          {caption}
        </p>
      ) : null}
    </Card>
  );
}

export interface KpiCardGroupProps extends HTMLAttributes<HTMLDivElement> {
  top?: ReactNode;
  bottom?: ReactNode;
  columns?: 2 | 3 | 4 | 5;
}

const kpiColumnClasses: Record<
  NonNullable<KpiCardGroupProps["columns"]>,
  string
> = {
  2: "sm:grid-cols-2",
  3: "sm:grid-cols-2 lg:grid-cols-3",
  4: "sm:grid-cols-2 lg:grid-cols-4",
  5: "sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5",
};

/**
 * Назначение функции: Объединяет верхнюю карточку, ряд KPI и нижнюю карточку в один блок с разделителями.
 * Зачем используется: KPI-сводки выглядят цельной композицией без внешних рамок и зазоров между карточками.
 */
export function KpiCardGroup({
  top,
  bottom,
  columns = 4,
  className,
  children,
  ...props
}: KpiCardGroupProps) {
  return (
    <div
      className={cn(
        "grid gap-px overflow-hidden rounded-[18px]  [&>[data-slot=card]]:!bg-[color:var(--border)]",
        className
      )}
      {...props}
    >
      {top}
      <div
        className={cn(
          "grid gap-px [&>[data-slot=card]]:rounded-none [&>[data-slot=card]:first-child]:rounded-l-[18px] [&>[data-slot=card]:last-child]:rounded-r-[18px]",
          kpiColumnClasses[columns]
        )}
      >
        {children}
      </div>
      {bottom}
    </div>
  );
}
