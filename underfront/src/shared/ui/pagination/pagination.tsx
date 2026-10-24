"use client";

import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/src/shared/lib/cn";
import { Button } from "../button";

interface PaginationProps {
  page: number;
  totalPages: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  className?: string;
  label?: ReactNode;
}

/**
 * Назначение функции: Отображает компонент `Pagination` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Pagination({
  page,
  totalPages,
  disabled,
  onPageChange,
  className,
  label,
}: PaginationProps) {
  const canPrev = page > 1;
  const canNext = page < totalPages;
  const totalPageDigits = String(Math.max(1, totalPages)).length;
  const counterCharacters = totalPageDigits * 2 + (label == null ? 3 : 1);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Button
        type="button"
        variant="back"
        className="!px-0"
        style={{ width: 36, minWidth: 36, height: 40 }}
        aria-label="Предыдущая страница"
        disabled={disabled || !canPrev}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft className="h-5 w-5" strokeWidth={2.5} aria-hidden />
      </Button>
      <span
        className="inline-block whitespace-nowrap text-center text-[18px] font-medium leading-[1.5] tracking-[0.025em] text-[#626262] tabular-nums"
        style={{ width: `${counterCharacters}ch` }}
      >
        {label ?? `${page} / ${totalPages}`}
      </span>
      <Button
        type="button"
        variant="back"
        className="!px-0"
        style={{ width: 36, minWidth: 36, height: 40 }}
        aria-label="Следующая страница"
        disabled={disabled || !canNext}
        onClick={() => onPageChange(page + 1)}
      >
        <ChevronRight className="h-5 w-5" strokeWidth={2.5} aria-hidden />
      </Button>
    </div>
  );
}
