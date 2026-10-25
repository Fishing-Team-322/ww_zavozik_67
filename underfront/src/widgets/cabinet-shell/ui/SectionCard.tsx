import { HTMLAttributes } from "react";
import { cn } from "@/src/shared/lib/cn";
import { Card } from "@/src/shared/ui/card";

type SectionCardProps = HTMLAttributes<HTMLDivElement>;

/**
 * Назначение функции: Отображает компонент `SectionCard` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function SectionCard({ className, ...props }: SectionCardProps) {
  return (
    <Card
      variant="content"
      className={cn(
        "min-w-0",
        className
      )}
      {...props}
    />
  );
}
