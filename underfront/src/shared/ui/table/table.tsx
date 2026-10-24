"use client";

import {
  createContext,
  useContext,
  HTMLAttributes,
  ReactNode,
  TableHTMLAttributes,
  TdHTMLAttributes,
  ThHTMLAttributes,
  useMemo,
  useState,
} from "react";
import { motion } from "motion/react";
import { cn } from "@/src/shared/lib/cn";
import { Pagination } from "@/src/shared/ui/pagination";

export type TableDensity = "compact" | "comfortable";
const DensityContext = createContext<TableDensity>("compact");
const cellSpacing: Record<TableDensity, string> = {
  compact: "px-3 py-2",
  comfortable: "px-4 py-3",
};
type CellTone = "default" | "muted" | "danger";
const cellTone: Record<CellTone, string> = {
  default: "text-[color:var(--text-primary)]",
  muted: "text-[color:var(--text-secondary)]",
  danger: "text-[color:var(--danger)]",
};

export type SortDirection = "none" | "desc" | "asc";

export type Column<T> = {
  key: keyof T & string;
  label: string;
  sortable?: boolean;
  className?: string;
  headerClassName?: string;
  render?: (value: T[keyof T], row: T) => ReactNode;
};

export interface SortState<T> {
  key: keyof T & string;
  direction: SortDirection;
}

export interface TablePaginationOptions {
  page: number;
  totalPages: number;
  disabled?: boolean;
  onPageChange: (page: number) => void;
}

type TableElementProps<T> = T & { unstyled?: boolean };

interface TableProps extends TableHTMLAttributes<HTMLTableElement> {
  /** Keep a composed table’s existing layout while reusing the shared overflow container. */
  unstyled?: boolean;
  /** Compact analytical rows by default; comfortable adds space for multiline content. */
  density?: TableDensity;
  /** Scenario/forecast comparison matrix with subtle alternating rows. */
  variant?: "default" | "matrix";
  pagination?: TablePaginationOptions;
}

/**
 * Назначение функции: Отображает компонент `Table` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function Table({
  className,
  pagination,
  density = "compact",
  variant = "default",
  unstyled = false,
  ...props
}: TableProps) {
  const totalPages = Math.max(1, pagination?.totalPages ?? 1);
  const page = Math.min(Math.max(1, pagination?.page ?? 1), totalPages);

  return (
    <DensityContext.Provider value={density}>
    <div className="flex h-full min-h-0 min-w-0 w-full flex-col">
      <div
        className={cn(
          "min-h-0 min-w-0 w-full flex-1 overflow-x-auto overflow-y-auto",
          "[scrollbar-width:thin]",
          "[scrollbar-color:color-mix(in_srgb,var(--text-secondary)_38%,transparent)_transparent]",
          "[&::-webkit-scrollbar]:h-2.5",
          "[&::-webkit-scrollbar]:w-2.5",
          "[&::-webkit-scrollbar-track]:bg-transparent",
          "[&::-webkit-scrollbar-thumb]:rounded-full",
          "[&::-webkit-scrollbar-thumb]:border-2",
          "[&::-webkit-scrollbar-thumb]:border-transparent",
          "[&::-webkit-scrollbar-thumb]:bg-clip-padding",
          "[&::-webkit-scrollbar-thumb]:bg-[color:color-mix(in_srgb,var(--text-secondary)_32%,transparent)]",
          "hover:[&::-webkit-scrollbar-thumb]:bg-[color:color-mix(in_srgb,var(--text-secondary)_48%,transparent)]"
        )}
      >
        <table
          className={cn(!unstyled && "w-full border-collapse text-[13px] leading-5", !unstyled && variant === "matrix" && "[&_tbody_tr:nth-child(odd)]:bg-[color:var(--surface-subtle)] [&_tbody_tr:hover]:bg-[color:var(--table-row-hover)]", className)}
          {...props}
        />
      </div>

      {pagination && <nav aria-label="Страницы таблицы" className="mt-4 flex justify-end">
        <Pagination
          page={page}
          totalPages={totalPages}
          disabled={pagination?.disabled}
          onPageChange={pagination?.onPageChange ?? (() => undefined)}
          label={`${page}/${totalPages}`}
        />
      </nav>}
    </div>
    </DensityContext.Provider>
  );
}

/**
 * Назначение функции: Отображает компонент `TableHeader` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function TableHeader({
  className,
  unstyled = false,
  ...props
}: TableElementProps<HTMLAttributes<HTMLTableSectionElement>>) {
  return (
    <thead
      className={cn(
        !unstyled && "sticky top-0 z-[1] border-b border-[color:var(--divider)] bg-[color:var(--surface)] [&_tr:hover]:bg-transparent",
        className
      )}
      {...props}
    />
  );
}

/**
 * Назначение функции: Отображает компонент `TableBody` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function TableBody({
  className,
  ...props
}: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn(className)} {...props} />;
}

/**
 * Назначение функции: Отображает компонент `TableRow` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function TableRow({
  className,
  unstyled = false,
  ...props
}: TableElementProps<HTMLAttributes<HTMLTableRowElement>>) {
  return (
    <tr
      className={cn(
        !unstyled && "border-b border-[color:var(--divider)] transition-colors hover:bg-[color:var(--table-row-hover)]",
        className
      )}
      {...props}
    />
  );
}

interface TableHeadProps extends ThHTMLAttributes<HTMLTableCellElement> {
  unstyled?: boolean;
  sortable?: boolean;
  sortDirection?: SortDirection;
  active?: boolean;
  onSortToggle?: () => void;
  numeric?: boolean;
  tone?: CellTone;
}

/**
 * Назначение функции: Отображает компонент `TableHead` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function TableHead({
  className,
  children,
  unstyled = false,
  sortable = false,
  sortDirection = "none",
  active = false,
  onSortToggle,
  numeric = false,
  tone,
  ...props
}: TableHeadProps) {
  const density = useContext(DensityContext);
  const isInteractive = sortable && typeof onSortToggle === "function";

  const ariaSort =
    sortDirection === "asc"
      ? "ascending"
      : sortDirection === "desc"
        ? "descending"
        : "none";

  return (
    <th
      className={cn(
        !unstyled && cn(cellSpacing[density], "align-middle text-xs font-medium leading-5", numeric ? "text-right tabular-nums" : "text-left", cellTone[tone ?? "muted"]),
        className
      )}
      aria-sort={isInteractive ? ariaSort : undefined}
      {...props}
    >
      {isInteractive ? (
        <motion.button
          type="button"
          data-active={active || undefined}
          onClick={onSortToggle}
          whileTap={{ y: 2 }}
          transition={{
            type: "spring",
            stiffness: 900,
            damping: 28,
            mass: 0.35,
          }}
          className={cn(
            "group inline-flex items-center gap-2 whitespace-nowrap text-inherit font-[inherit] leading-[inherit] transition-colors duration-200",
            numeric && "justify-end",
            "cursor-pointer hover:text-[color:var(--text-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring-strong)]"
          )}
        >
          <span>{children}</span>

          <span className="relative inline-flex h-4 w-4 shrink-0 items-center justify-center">
            <motion.span
              animate={{
                opacity: sortDirection === "none" ? 0 : 1,
                scale: sortDirection === "none" ? 0.8 : 1,
                y: sortDirection === "none" ? -2 : 0,
                rotate: sortDirection === "asc" ? 180 : 0,
              }}
              transition={{ duration: 0.18 }}
              className="absolute inset-0 flex items-center justify-center"
            >
              <ChevronIcon className="text-current" />
            </motion.span>
          </span>
        </motion.button>
      ) : unstyled ? children : (
        <span className="whitespace-nowrap">
          {children}
        </span>
      )}
    </th>
  );
}

/**
 * Назначение функции: Отображает компонент `TableCell` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function TableCell({
  className,
  unstyled = false,
  numeric = false,
  highlighted = false,
  tone = "default",
  ...props
}: TableElementProps<TdHTMLAttributes<HTMLTableCellElement>> & { numeric?: boolean; tone?: CellTone; highlighted?: boolean }) {
  const density = useContext(DensityContext);
  return (
    <td
      className={cn(
        !unstyled && cn(cellSpacing[density], "align-middle text-[13px] font-normal leading-5", cellTone[tone], numeric && "text-right tabular-nums", highlighted && "bg-[color:var(--accent-soft)]"),
        className
      )}
      {...props}
    />
  );
}

/**
 * Назначение функции: Отображает компонент `ChevronIcon` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function ChevronIcon({ className }: { className?: string }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 14 14"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
    >
      <path
        d="M3.5 5.25L7 8.75L10.5 5.25"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Назначение функции: Возвращает данные объекта «порядок сортировки»; операция `getNextSortDirection`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function getNextSortDirection(direction: SortDirection): SortDirection {
  if (direction === "none") return "desc";
  if (direction === "desc") return "asc";
  return "none";
}

/**
 * Назначение функции: Сравнивает данные объекта «значение»; операция `compareValues`.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
function compareValues(a: unknown, b: unknown) {
  if (typeof a === "number" && typeof b === "number") {
    return a - b;
  }

  if (a instanceof Date && b instanceof Date) {
    return a.getTime() - b.getTime();
  }

  return String(a ?? "").localeCompare(String(b ?? ""), "ru", {
    numeric: true,
    sensitivity: "base",
  });
}

interface MinimalSortableTableProps<T> {
  data: T[];
  columns: Column<T>[];
  initialSort?: SortState<T> | null;
  rowKey: (row: T, index: number) => string;
  className?: string;
  onSortChange?: (sort: SortState<T> | null) => void;
  onRowClick?: (row: T, index: number) => void;
  pagination?: {
    page: number;
    totalPages: number;
    pageSize?: number;
    disabled?: boolean;
    onPageChange: (page: number) => void;
  };
}

/**
 * Назначение функции: Отображает компонент `MinimalSortableTable` и связывает его входные данные с JSX-разметкой.
 * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
 */
export function MinimalSortableTable<T extends Record<string, unknown>>({
  data,
  columns,
  initialSort = null,
  rowKey,
  className,
  onSortChange,
  onRowClick,
  pagination,
}: MinimalSortableTableProps<T>) {
  const [sort, setSort] = useState<SortState<T> | null>(initialSort);

  const sortedData = useMemo(() => {
    if (!sort || sort.direction === "none") return data;

    const copied = [...data];

    copied.sort((a, b) => {
      const result = compareValues(a[sort.key], b[sort.key]);
      return sort.direction === "asc" ? result : -result;
    });

    return copied;
  }, [data, sort]);

  const totalPages = Math.max(1, pagination?.totalPages ?? 1);
  const currentPageNumber = pagination?.page ?? 1;
  const pageSize = pagination?.pageSize;
  const visibleData = useMemo(() => {
    if (!pageSize) return sortedData;

    const page = Math.min(Math.max(1, currentPageNumber), totalPages);
    const start = (page - 1) * pageSize;

    return sortedData.slice(start, start + pageSize);
  }, [currentPageNumber, pageSize, sortedData, totalPages]);

  /**
   * Назначение функции: Обрабатывает данные объекта «порядок сортировки»; операция `handleToggleSort`.
   * Зачем используется: Позволяет повторно использовать элемент интерфейса и его поведение.
   */
  const handleToggleSort = (key: keyof T & string) => {
    setSort((prev) => {
      if (!prev || prev.key !== key) {
        const next: SortState<T> = { key, direction: "desc" };
        onSortChange?.(next);
        return next;
      }

      const nextDirection = getNextSortDirection(prev.direction);

      if (nextDirection === "none") {
        onSortChange?.(null);
        return null;
      }

      const next: SortState<T> = { key, direction: nextDirection };
      onSortChange?.(next);
      return next;
    });
  };

  return (
    <Table
      className={className}
      pagination={
        pagination
          ? {
              page: currentPageNumber,
              totalPages,
              disabled: pagination.disabled,
              onPageChange: pagination.onPageChange,
            }
          : undefined
      }
    >
      <TableHeader>
        <tr>
          {columns.map((column) => {
            const active = sort?.key === column.key;
            const direction = active ? sort.direction : "none";

            return (
              <TableHead
                key={column.key}
                className={column.headerClassName}
                sortable={Boolean(column.sortable)}
                active={Boolean(active)}
                sortDirection={direction}
                onSortToggle={
                  column.sortable
                    ? () => handleToggleSort(column.key)
                    : undefined
                }
              >
                {column.label}
              </TableHead>
            );
          })}
          {onRowClick ? (
            <TableHead
              aria-label="Переход к записи"
              className="w-10 px-2"
            />
          ) : null}
        </tr>
      </TableHeader>

      <TableBody>
        {visibleData.map((row, index) => (
          <TableRow
            key={rowKey(row, index)}
            className={onRowClick ? "group cursor-pointer" : undefined}
            onClick={onRowClick ? () => onRowClick(row, index) : undefined}
          >
            {columns.map((column) => {
              const value = row[column.key];

              return (
                <TableCell key={column.key} className={column.className}>
                  {column.render
                    ? column.render(value, row)
                    : String(value ?? "")}
                </TableCell>
              );
            })}
            {onRowClick ? (
              <TableCell className="w-10 px-2 text-right">
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 16 16"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden="true"
                  className="ml-auto text-[color:var(--text-secondary)] transition-colors duration-200 group-hover:text-[color:var(--text-primary)]"
                >
                  <path
                    d="M2.5 8H12.5M8.5 4L12.5 8L8.5 12"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </TableCell>
            ) : null}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
