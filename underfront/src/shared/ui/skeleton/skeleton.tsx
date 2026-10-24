import { HTMLAttributes } from "react";
import { cn } from "@/src/shared/lib/cn";

type SkeletonProps = HTMLAttributes<HTMLDivElement>;

/**
 * Назначение функции: Отображает компонент `Skeleton` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-xl bg-[color:var(--surface-muted)]",
        className
      )}
      {...props}
    />
  );
}
