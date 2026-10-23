"use client";

import { useId, useLayoutEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { Activity, CalendarDays, ChartNoAxesCombined, ChevronDown, FileSpreadsheet, FlaskConical, LayoutDashboard, LayoutGrid, ShieldAlert, SlidersHorizontal, Wallet, X } from "lucide-react";
import { cn } from "@/src/lib/cn";
import { useSidebarNavState } from "./SidebarNavStateProvider";

/** A small, application-independent replacement for the old role-based navigation. */
export type SidebarNavItem = {
  href: string;
  label: string;
  icon?: LucideIcon;
  section?: string;
  disabled?: boolean;
};

export const defaultCabinetNav: SidebarNavItem[] = [
  { href: "/", label: "Обзор", icon: LayoutDashboard, section: "Рабочее пространство" },
  { href: "/transactions", label: "Операции", icon: Wallet, section: "Рабочее пространство" },
  { href: "/forecast", label: "Прогноз", icon: ChartNoAxesCombined, section: "Аналитика" },
  { href: "/scenarios", label: "Сценарии", icon: SlidersHorizontal, section: "Аналитика" },
  { href: "/risks", label: "Кассовые разрывы", icon: ShieldAlert, section: "Аналитика" },
  { href: "/calendar", label: "Календарь платежей", icon: CalendarDays, section: "Планирование" },
  { href: "/sources", label: "Источники данных", icon: FileSpreadsheet, section: "Планирование" },
  { href: "/development/components", label: "Кнопки и поля", icon: LayoutGrid, section: "Разработка" },
  { href: "/test", label: "Все компоненты", icon: FlaskConical, section: "Разработка" },
];

const fallbackIcon = Activity;
const isActiveItem = (href: string, pathname: string) =>
  href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

export function SidebarNav({ items = defaultCabinetNav, onNavigate }: { items?: SidebarNavItem[]; onNavigate?: () => void }) {
  const pathname = usePathname() || "/";
  const navId = useId();
  const sections = Array.from(new Set(items.map((item) => item.section ?? "Навигация")));
  const activeSection = sections.find((section) =>
    items.some((item) => (item.section ?? "Навигация") === section && isActiveItem(item.href, pathname))
  );
  const { expandedSections, openSection, toggleSection } = useSidebarNavState();
  const visibleExpandedSections = expandedSections ?? (activeSection ? [activeSection] : []);

  useLayoutEffect(() => {
    if (activeSection) openSection(activeSection);
  }, [activeSection, openSection]);

  return (
    <nav aria-label="Основная навигация" className="flex-1 overflow-y-auto px-3 pb-4">
      <ul className="space-y-2">
        {sections.map((section, index) => {
          const sectionItems = items.filter((item) => (item.section ?? "Навигация") === section);
          const GroupIcon = sectionItems[0]?.icon ?? fallbackIcon;
          const expanded = visibleExpandedSections.includes(section);
          const panelId = `${navId}-section-${index}`;
          return (
            <li key={section}>
              <button
                type="button"
                aria-expanded={expanded}
                aria-controls={panelId}
                onClick={() => toggleSection(section, visibleExpandedSections)}
                className={cn(
                  "flex w-full items-center rounded-[6px] px-3 py-2 text-left text-[14px] font-medium leading-4 tracking-normal tabular-nums transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--focus-ring-strong)]",
                  section === activeSection ? "text-[color:var(--nav-item-active-text)]" : "text-[color:var(--nav-item-text-muted)] hover:text-[color:var(--nav-item-text-hover)]"
                )}
              >
                <GroupIcon className="mr-2.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span className="min-w-0 truncate">{section}</span>
                <ChevronDown className={cn("ml-1 h-4 w-4 shrink-0 transition-transform", !expanded && "-rotate-90")} aria-hidden="true" />
              </button>
              <ul id={panelId} hidden={!expanded} className="mt-0.5">
                {sectionItems.map((item) => {
                  const Icon = item.icon ?? fallbackIcon;
                  const active = isActiveItem(item.href, pathname);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.disabled ? "#" : item.href}
                        onClick={(event) => { if (item.disabled) { event.preventDefault(); return; } onNavigate?.(); }}
                        aria-current={active ? "page" : undefined}
                        aria-disabled={item.disabled || undefined}
                        className={cn(
                          "group flex w-full items-center gap-2.5 rounded-[6px] py-1.5 pl-6 pr-3 text-[14px] font-medium leading-4 tracking-normal tabular-nums transition-colors",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--focus-ring-strong)]",
                          active ? "bg-[color:var(--sidebar-active)] text-[color:var(--nav-item-active-text)]" : "text-[color:var(--nav-item-text)] hover:text-[color:var(--nav-item-text-hover)]",
                          item.disabled && "pointer-events-none opacity-45"
                        )}
                      >
                        <Icon className={cn("h-4 w-4 shrink-0", active ? "text-[color:var(--nav-item-icon-active)]" : "text-[color:var(--nav-item-icon)] group-hover:text-[color:var(--nav-item-icon-hover)]")} aria-hidden="true" />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function SidebarBrand({ title = "ПУЛЬС", subtitle = "Финансовый радар", onClose }: { title?: string; subtitle?: string; onClose?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-4">
      <Link href="/" className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[8px] bg-[image:var(--brand-gradient)] text-white shadow-[var(--shadow-xs)]"><Activity size={16}/></span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[14px] font-semibold leading-4 text-[color:var(--text-primary)]">{title}</span>
          <span className="truncate text-[11px] leading-4 text-[color:var(--text-secondary)]">{subtitle}</span>
        </span>
      </Link>
      {onClose ? <button type="button" className="rounded-[6px] p-2 text-[color:var(--text-secondary)] hover:text-[color:var(--text-primary)] lg:hidden" aria-label="Закрыть меню" onClick={onClose}><X size={16}/></button> : null}
    </div>
  );
}
