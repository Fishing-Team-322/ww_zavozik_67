import Link from "next/link";
import { ChevronRight, type LucideIcon } from "lucide-react";
import { cn } from "@/src/lib/cn";

export type BreadcrumbItem = {
  label: string;
  icon: LucideIcon;
  href?: string;
};

export type BreadcrumbsProps = {
  items: readonly BreadcrumbItem[];
  className?: string;
  ariaLabel?: string;
};

/** Shows the section first, followed by each nested page. */
export function Breadcrumbs({ items, className, ariaLabel = "Навигационная цепочка" }: BreadcrumbsProps) {
  if (items.length === 0) return null;

  return (
    <nav aria-label={ariaLabel} className={cn("min-w-0", className)}>
      <ol className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm font-medium leading-5">
        {items.map((item, index) => {
          const Icon = item.icon;
          const current = index === items.length - 1;
          const content = (
            <>
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{item.label}</span>
            </>
          );

          return (
            <li key={`${item.label}-${index}`} className="inline-flex min-w-0 items-center gap-2.5">
              {index > 0 ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[color:var(--text-muted)]" aria-hidden="true" /> : null}
              {current ? (
                <span aria-current="page" className="inline-flex items-center gap-1.5 whitespace-nowrap text-[color:var(--text-primary)]">
                  {content}
                </span>
              ) : item.href ? (
                <Link href={item.href} className="inline-flex items-center gap-1.5 whitespace-nowrap text-[color:var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]">
                  {content}
                </Link>
              ) : (
                <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[color:var(--text-primary)]">
                  {content}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
