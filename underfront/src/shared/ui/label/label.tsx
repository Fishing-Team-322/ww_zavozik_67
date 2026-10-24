import { LabelHTMLAttributes } from "react";
import { cn } from "@/src/shared/lib/cn";

type LabelProps = LabelHTMLAttributes<HTMLLabelElement>;

/**
 * Назначение функции: Отображает компонент `Label` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Label({ className, ...props }: LabelProps) {
  return (
    <label
      className={cn(
        "text-sm font-medium leading-none text-[color:var(--text-primary)]",
        className
      )}
      {...props}
    />
  );
}
