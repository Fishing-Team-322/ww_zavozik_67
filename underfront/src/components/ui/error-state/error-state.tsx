import { ReactNode } from "react";
import { CircleAlert } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface ErrorStateProps {
  title?: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

/** Назначение функции: Показывает сбой загрузки с пояснением и действием восстановления, сохраняя контекст текущего раздела.
 * Зачем используется: Даёт понятное восстановление после сбоя, не подменяя его сообщением об отсутствии записей.
 */
export function ErrorState({
  title = "Что-то пошло не так",
  description,
  action,
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-2xl border border-[color:var(--badge-border)] bg-[color:var(--badge-bg)] p-6 text-center",
        className
      )}
    >
      <CircleAlert aria-hidden="true" className="mx-auto mb-3 h-7 w-7 text-[var(--danger)]" />
      <h3 className="text-base font-semibold text-[color:var(--danger)]">
        {title}
      </h3>
      {description ? (
        <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-[color:var(--text-secondary)]">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}
