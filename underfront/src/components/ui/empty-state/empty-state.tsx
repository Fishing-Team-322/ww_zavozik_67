import { ReactNode } from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/src/lib/cn";

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

/** Назначение функции: Объясняет отсутствие данных и предлагает следующий шаг, чтобы пустой реестр не выглядел как ошибка или загрузка.
 * Зачем используется: Отличает успешную пустую выборку от сбоя и помогает пользователю создать запись или изменить фильтры.
 */
export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        [
          "rounded-2xl",
          "border border-dashed border-[color:var(--border-muted)]",
          "bg-[var(--surface)]",
          "px-5 py-8 sm:px-8",
          "text-center",
        ],
        className
      )}
    >
      <Inbox aria-hidden="true" className="mx-auto mb-3 h-7 w-7 text-[var(--text-muted)]" />
      <h3 className="text-base font-semibold text-[color:var(--text-primary)]">
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
