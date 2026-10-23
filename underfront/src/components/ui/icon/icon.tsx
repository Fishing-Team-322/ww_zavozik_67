import { type LucideIcon } from "lucide-react";
import { cn } from "@/src/lib/cn";

export const ICON_SIZE = {
  sm: 16,
  md: 18,
  lg: 20,
} as const;

export const ICON_STROKE_WIDTH = 2;

export type IconTone = "primary" | "muted" | "success" | "danger";
export type IconSize = keyof typeof ICON_SIZE;

const iconToneClassName: Record<IconTone, string> = {
  primary: "text-[color:var(--text-primary)]",
  muted: "text-[color:var(--text-secondary)]",
  success: "text-[color:var(--success)]",
  danger: "text-[color:var(--danger)]",
};

type IconProps = {
  icon: LucideIcon;
  size?: IconSize;
  tone?: IconTone;
  className?: string;
};

/**
 * Назначение функции: Отображает компонент `Icon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Icon({
  icon: Lucide,
  size = "md",
  tone = "muted",
  className,
}: IconProps) {
  return (
    <Lucide
      size={ICON_SIZE[size]}
      strokeWidth={ICON_STROKE_WIDTH}
      className={cn(iconToneClassName[tone], className)}
      aria-hidden="true"
    />
  );
}
