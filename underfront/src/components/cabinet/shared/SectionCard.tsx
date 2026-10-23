import { HTMLAttributes } from "react";
import { cn } from "@/src/lib/cn";
import { Card } from "@/src/components/ui/card";

type SectionCardProps = HTMLAttributes<HTMLDivElement>;

/**
 * Назначение функции: Отображает компонент `SectionCard` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет экранам использовать общий механизм без дублирования реализации.
 */
export function SectionCard({ className, ...props }: SectionCardProps) {
  return (
    <Card
      className={cn(
        "rounded-[18px] border border-[color:var(--border)] bg-[color:var(--card-bg)] shadow-[0_4px_12px_rgba(15,38,72,0.03)]",
        className
      )}
      {...props}
    />
  );
}
