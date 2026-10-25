"use client";

import { forwardRef, useId, useLayoutEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon, LucideProps } from "lucide-react";
import { Activity, ChevronDown, FileSpreadsheet, SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/src/shared/lib/cn";
import { useSidebarNavState } from "./SidebarNavStateProvider";

/** A small, application-independent replacement for the old role-based navigation. */
export type SidebarNavItem = {
  href: string;
  label: string;
  icon?: LucideIcon;
  section?: string;
  taskNumber?: string;
  disabled?: boolean;
};

// Font Awesome Free v7.3.1 by Fonticons, Inc. (https://fontawesome.com/license/free), copyright 2026.
const OverviewHomeIcon = forwardRef<SVGSVGElement, LucideProps>(function OverviewHomeIcon({ size = 24, ...props }, ref) {
  return (
    <svg ref={ref} viewBox="0 0 640 640" width={size} height={size} fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M341.8 72.6C329.5 61.2 310.5 61.2 298.3 72.6L74.3 280.6C64.7 289.6 61.5 303.5 66.3 315.7C71.1 327.9 82.8 336 96 336L112 336L112 512C112 547.3 140.7 576 176 576L464 576C499.3 576 528 547.3 528 512L528 336L544 336C557.2 336 569 327.9 573.8 315.7C578.6 303.5 575.4 289.5 565.8 280.6L341.8 72.6zM304 384L336 384C362.5 384 384 405.5 384 432L384 528L256 528L256 432C256 405.5 277.5 384 304 384z" />
    </svg>
  );
});

function createFilledIcon(name: string, path: string): LucideIcon {
  const Icon = forwardRef<SVGSVGElement, LucideProps>(function FilledIcon({ size = 24, ...props }, ref) {
    return (
      <svg ref={ref} viewBox="0 0 24 24" width={size} height={size} fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
        <path d={path} />
      </svg>
    );
  });
  Icon.displayName = name;
  return Icon;
}

const WorkspaceIcon = createFilledIcon("WorkspaceIcon", "M12.3096 20.0951C12.416 21.1598 11.6638 22.1195 10.6045 22.2708 9.66941 22.4042 8.76909 21.8636 8.44629 20.9759L7 17.0004H12L12.3096 20.0951ZM19.4453 2.03658C20.1099 1.59354 21 2.06991 21 2.8686V18.1312C21 18.9299 20.1099 19.4063 19.4453 18.9632L15 16.0004H7.5C4.46258 16.0004 2.00024 13.5377 2 10.5004C2 7.46285 4.46243 5.00043 7.5 5.00043H15L19.4453 2.03658Z");
const PlanningIcon = createFilledIcon("PlanningIcon", "M10 10.1111V1L21 7V21H3V7L10 10.1111Z");
const TransactionsIcon = createFilledIcon("TransactionsIcon", "M9.3349 11.5023L11.5049 11.5028C13.9902 11.5028 16.0049 13.5175 16.0049 16.0028H9.00388L9.00488 17.0028L17.0049 17.002V16.0028C17.0049 14.9204 16.6867 13.8997 16.1188 13.002L19.0049 13.0028C20.9972 13.0028 22.7173 14.1681 23.521 15.8542C21.1562 18.9748 17.3268 21.0028 13.0049 21.0028C10.2436 21.0028 7.90445 20.4122 6.00456 19.378L6.00592 10.0738C7.25147 10.2522 8.39122 10.7585 9.3349 11.5023ZM5.00488 19.0028C5.00488 19.5551 4.55717 20.0028 4.00488 20.0028H2.00488C1.4526 20.0028 1.00488 19.5551 1.00488 19.0028V10.0028C1.00488 9.45052 1.4526 9.00281 2.00488 9.00281H4.00488C4.55717 9.00281 5.00488 9.45052 5.00488 10.0028V19.0028ZM18.0049 5.00281C19.6617 5.00281 21.0049 6.34595 21.0049 8.00281C21.0049 9.65966 19.6617 11.0028 18.0049 11.0028C16.348 11.0028 15.0049 9.65966 15.0049 8.00281C15.0049 6.34595 16.348 5.00281 18.0049 5.00281ZM11.0049 2.00281C12.6617 2.00281 14.0049 3.34595 14.0049 5.00281C14.0049 6.65966 12.6617 8.00281 11.0049 8.00281C9.34803 8.00281 8.00488 6.65966 8.00488 5.00281C8.00488 3.34595 9.34803 2.00281 11.0049 2.00281Z");
const ForecastIcon = createFilledIcon("ForecastIcon", "M3 3H21C21.5523 3 22 3.44772 22 4V20C22 20.5523 21.5523 21 21 21H3C2.44772 21 2 20.5523 2 20V4C2 3.44772 2.44772 3 3 3ZM7 13V17H9V13H7ZM11 7V17H13V7H11ZM15 10V17H17V10H15Z");
const CashShortfallsIcon = createFilledIcon("CashShortfallsIcon", "M1 5C1 4.44772 1.44772 4 2 4H22C22.5523 4 23 4.44772 23 5V19C23 19.5523 22.5523 20 22 20H2C1.44772 20 1 19.5523 1 19V5ZM9 8H7V10H9V8ZM7 13V16H9V11H6V13H7ZM13 9V11H19V9H13ZM18 13H13V15H18V13Z");
const PaymentCalendarIcon = createFilledIcon("PaymentCalendarIcon", "M17 3H21C21.5523 3 22 3.44772 22 4V20C22 20.5523 21.5523 21 21 21H3C2.44772 21 2 20.5523 2 20V4C2 3.44772 2.44772 3 3 3H7V1H9V3H15V1H17V3ZM4 9V19H20V9H4ZM6 11H8V13H6V11ZM6 15H8V17H6V15ZM10 11H18V13H10V11ZM10 15H15V17H10V15Z");

const StarsIcon = forwardRef<SVGSVGElement, LucideProps>(function StarsIcon({ size = 24, ...props }, ref) {
  return (
    <svg ref={ref} viewBox="0 0 24 24" width={size} height={size} fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path fill="currentColor" d="M10.22 4.24C11 2.72 11.39 1.95 12 1.95s1 .77 1.78 2.3l1.35 2.65c.23.44.34.66.54.8s.44.18.93.26l2.94.47c1.7.27 2.54.4 2.73.99c.2.58-.42 1.19-1.63 2.4l-2.1 2.1c-.35.36-.53.53-.6.76c-.08.23-.04.48.04.97l.46 2.94c.27 1.7.4 2.54-.1 2.9c-.49.36-1.25-.03-2.78-.8l-2.65-1.36c-.45-.22-.67-.33-.91-.33s-.46.1-.9.33l-2.66 1.35c-1.53.78-2.3 1.17-2.79.81s-.36-1.2-.1-2.9l.47-2.94c.08-.5.12-.74.04-.97s-.25-.4-.6-.76l-2.1-2.1C2.15 10.6 1.54 10 1.73 9.42c.19-.59 1.03-.72 2.73-.99l2.94-.47c.5-.08.74-.12.93-.26s.3-.36.54-.8z" />
      <path stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M10.22 4.24C11 2.72 11.39 1.95 12 1.95s1 .77 1.78 2.3l1.35 2.65c.23.44.34.66.54.8s.44.18.93.26l2.94.47c1.7.27 2.54.4 2.73.99c.2.58-.42 1.19-1.63 2.4l-2.1 2.1c-.35.36-.53.53-.6.76c-.08.23-.04.48.04.97l.46 2.94c.27 1.7.4 2.54-.1 2.9c-.49.36-1.25-.03-2.78-.8l-2.65-1.36c-.45-.22-.67-.33-.91-.33s-.46.1-.9.33l-2.66 1.35c-1.53.78-2.3 1.17-2.79.81s-.36-1.2-.1-2.9l.47-2.94c.08-.5.12-.74.04-.97s-.25-.4-.6-.76l-2.1-2.1C2.15 10.6 1.54 10 1.73 9.42c.19-.59 1.03-.72 2.73-.99l2.94-.47c.5-.08.74-.12.93-.26s.3-.36.54-.8z" />
    </svg>
  );
});

const PlanFactIcon = forwardRef<SVGSVGElement, LucideProps>(function PlanFactIcon({ size = 24, ...props }, ref) {
  const maskId = useId();
  return (
    <svg ref={ref} viewBox="0 0 48 48" width={size} height={size} xmlns="http://www.w3.org/2000/svg" {...props}>
      <defs>
        <mask id={maskId}>
          <g fill="none" strokeWidth="4">
            <path fill="#fff" stroke="#fff" strokeLinejoin="round" d="M5 19h38v22a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z" />
            <path stroke="#fff" strokeLinejoin="round" d="M5 10a2 2 0 0 1 2-2h34a2 2 0 0 1 2 2v9H5z" />
            <path stroke="#000" strokeLinecap="round" strokeLinejoin="round" d="m16 31l6 6l12-12" />
            <path stroke="#fff" strokeLinecap="round" d="M16 5v8m16-8v8" />
          </g>
        </mask>
      </defs>
      <path fill="currentColor" d="M0 0h48v48H0z" mask={`url(#${maskId})`} />
    </svg>
  );
});

const SourcesIcon = forwardRef<SVGSVGElement, LucideProps>(function SourcesIcon({ size = 24, ...props }, ref) {
  return (
    <svg ref={ref} viewBox="0 0 16 16" width={size} height={size} fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M6.5 0A1.5 1.5 0 0 0 5 1.5v1A1.5 1.5 0 0 0 6.5 4h3A1.5 1.5 0 0 0 11 2.5v-1A1.5 1.5 0 0 0 9.5 0zm3 1a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-.5.5h-3a.5.5 0 0 1-.5-.5v-1a.5.5 0 0 1 .5-.5z" />
      <path d="M4 1.5H3a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V3.5a2 2 0 0 0-2-2h-1v1A2.5 2.5 0 0 1 9.5 5h-3A2.5 2.5 0 0 1 4 2.5zM10 8a1 1 0 1 1 2 0v5a1 1 0 1 1-2 0zm-6 4a1 1 0 1 1 2 0v1a1 1 0 1 1-2 0zm4-3a1 1 0 0 1 1 1v3a1 1 0 1 1-2 0v-3a1 1 0 0 1 1-1" />
    </svg>
  );
});

const CounterpartiesIcon = forwardRef<SVGSVGElement, LucideProps>(function CounterpartiesIcon({ size = 24, ...props }, ref) {
  return (
    <svg ref={ref} viewBox="0 0 16 16" width={size} height={size} fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M8 2.002a1.998 1.998 0 1 0 0 3.996a1.998 1.998 0 0 0 0-3.996M12.5 3a1.5 1.5 0 1 0 0 3a1.5 1.5 0 0 0 0-3m-9 0a1.5 1.5 0 1 0 0 3a1.5 1.5 0 0 0 0-3M5 7.993A1 1 0 0 1 6 7h4a1 1 0 0 1 1 1v3a3 3 0 0 1-.146.927A3.001 3.001 0 0 1 5 11zM4 8c0-.365.097-.706.268-1H2a1 1 0 0 0-1 1v2.5a2.5 2.5 0 0 0 3.436 2.319A4 4 0 0 1 4 10.999zm8 0v3c0 .655-.157 1.273-.436 1.819A2.5 2.5 0 0 0 15 10.5V8a1 1 0 0 0-1-1h-2.268c.17.294.268.635.268 1" />
    </svg>
  );
});

const MethodologyIcon = forwardRef<SVGSVGElement, LucideProps>(function MethodologyIcon({ size = 24, ...props }, ref) {
  return (
    <svg ref={ref} viewBox="0 0 24 24" width={size} height={size} fill="currentColor" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M8 3H6v3H3v2h3v3h2V8h3V6H8zm5 3h8v2h-8zm0 8h8v2h-8zm0 4h8v2h-8zm-3.46-4.96L7 15.59l-2.54-2.55l-1.42 1.42L5.59 17l-2.55 2.54l1.42 1.42L7 18.41l2.54 2.55l1.42-1.42L8.41 17l2.55-2.54z" />
    </svg>
  );
});

export const sidebarSectionIcons: Record<string, LucideIcon> = {
  Обязательное: WorkspaceIcon,
  Звёздочки: StarsIcon,
  Дополнительно: PlanningIcon,
};

export const defaultCabinetNav: SidebarNavItem[] = [
  { href: "/overview", label: "Обзор", icon: OverviewHomeIcon, section: "Обязательное" },
  { href: "/forecast", label: "Прогноз", icon: ForecastIcon, section: "Обязательное" },
  { href: "/risks", label: "Нехватка денег", icon: CashShortfallsIcon, section: "Обязательное" },
  { href: "/transactions", label: "Операции", icon: TransactionsIcon, section: "Обязательное" },
  { href: "/recurring", label: "Регулярные платежи", icon: PaymentCalendarIcon, section: "Обязательное" },
  { href: "/documents", label: "Документы", icon: FileSpreadsheet, section: "Звёздочки", taskNumber: "01" },
  { href: "/plan-fact", label: "План-факт", icon: PlanFactIcon, section: "Звёздочки", taskNumber: "02" },
  { href: "/scenarios", label: "Сценарии", icon: SlidersHorizontal, section: "Звёздочки", taskNumber: "03" },
  { href: "/sources", label: "Источники данных", icon: SourcesIcon, section: "Звёздочки", taskNumber: "04" },
  { href: "/calendar", label: "Платёжный календарь", icon: PaymentCalendarIcon, section: "Дополнительно" },
  { href: "/taxes", label: "Налоги", icon: FileSpreadsheet, section: "Дополнительно" },
  { href: "/counterparties", label: "Контрагенты", icon: CounterpartiesIcon, section: "Дополнительно" },
  { href: "/notifications", label: "Уведомления", icon: Activity, section: "Дополнительно" },
  { href: "/methodology", label: "Проверка прогнозов", icon: MethodologyIcon, section: "Дополнительно" },
  { href: "/settings", label: "Настройки", icon: SlidersHorizontal, section: "Дополнительно" },
];

const fallbackIcon = Activity;
const isActiveItem = (href: string, pathname: string) =>
  href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);

function NavItemLink({ item, pathname, onNavigate, nested = false }: { item: SidebarNavItem; pathname: string; onNavigate?: () => void; nested?: boolean }) {
  const Icon = item.icon ?? fallbackIcon;
  const active = isActiveItem(item.href, pathname);

  return (
    <Link
      href={item.disabled ? "#" : item.href}
      onClick={(event) => { if (item.disabled) { event.preventDefault(); return; } onNavigate?.(); }}
      aria-current={active ? "page" : undefined}
      aria-disabled={item.disabled || undefined}
      className={cn(
        "group flex h-8 w-full min-w-0 items-center gap-2 rounded-[5px] px-2 text-[14px] font-medium leading-4 tracking-normal tabular-nums transition-colors",
        nested && "pl-[18px]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)]",
        active ? "bg-[color:var(--nav-item-active-bg)] text-[color:var(--nav-item-active-text)]" : "text-[color:var(--nav-item-text)] hover:bg-[color:var(--nav-item-hover-bg)] hover:text-[color:var(--nav-item-text-hover)]",
        item.disabled && "pointer-events-none opacity-45"
      )}
    >
      <Icon className={cn("h-[15px] w-[15px] shrink-0", active ? "text-[color:var(--nav-item-icon-active)]" : "text-[color:var(--nav-item-icon)] group-hover:text-[color:var(--nav-item-icon-hover)]")} aria-hidden="true" />
      <span className="min-w-0 truncate">{item.label}</span>
      {item.taskNumber ? <span className="ml-auto shrink-0 text-[10px] font-normal text-[color:var(--nav-item-text-muted)]">{item.taskNumber}</span> : null}
    </Link>
  );
}

export function SidebarUtilityNav({ item, onNavigate }: { item?: SidebarNavItem; onNavigate?: () => void }) {
  const pathname = usePathname() || "/";
  if (!item) return null;

  return (
    <nav aria-label="Additional navigation">
      <NavItemLink item={item} pathname={pathname} onNavigate={onNavigate} />
    </nav>
  );
}

export function SidebarNav({ items = defaultCabinetNav, onNavigate }: { items?: SidebarNavItem[]; onNavigate?: () => void }) {
  const pathname = usePathname() || "/";
  const navId = useId();
  const mainItems = items.filter((item) => item.href !== "/settings" && item.section !== "Development" && item.section !== "Разработка");
  const sections = Array.from(new Set(mainItems.map((item) => item.section ?? "Navigation")));
  const activeSection = sections.find((section) =>
    mainItems.some((item) => (item.section ?? "Navigation") === section && isActiveItem(item.href, pathname))
  );
  const { expandedSections, openSection, toggleSection } = useSidebarNavState();
  const visibleExpandedSections = expandedSections ?? (activeSection ? [activeSection] : []);

  useLayoutEffect(() => {
    if (activeSection) openSection(activeSection);
  }, [activeSection, openSection]);

  return (
    <nav aria-label="Main navigation" className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
      <ul className="space-y-2.5">
        {sections.map((section, index) => {
          const sectionItems = mainItems.filter((item) => (item.section ?? "Navigation") === section);
          const SectionIcon = sidebarSectionIcons[section];
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
                  "flex h-7 w-full items-center rounded-[5px] px-2 text-left text-[14px] font-medium leading-4 tracking-normal tabular-nums transition-colors hover:bg-[color:var(--nav-item-hover-bg)]",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)]",
                  section === activeSection ? "text-[color:var(--nav-item-active-text)]" : "text-[color:var(--nav-item-text)] hover:text-[color:var(--nav-item-text-hover)]"
                )}
              >
                {SectionIcon ? <SectionIcon className="mr-2 h-[15px] w-[15px] shrink-0" aria-hidden="true" /> : null}
                <span className="min-w-0 truncate">{section}</span>
                <ChevronDown className={cn("ml-1 h-[13px] w-[13px] shrink-0 transition-transform", !expanded && "-rotate-90")} aria-hidden="true" />
              </button>
              <ul id={panelId} hidden={!expanded}>
                {sectionItems.map((item) => {
                  return (
                    <li key={item.href}>
                      <NavItemLink item={item} pathname={pathname} onNavigate={onNavigate} nested />
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

export function SidebarBrand({ title = "PULSE", subtitle = "Financial radar", onClose }: { title?: string; subtitle?: string; onClose?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <Link href="/overview" className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] bg-[color:var(--sidebar-active)] text-[color:var(--nav-item-active-text)]"><Activity size={15}/></span>
        <span className="flex min-w-0 flex-col">
          <span className="truncate text-[14px] font-semibold leading-4 text-[color:var(--nav-item-active-text)]">{title}</span>
          <span className="truncate text-[11px] leading-4 text-[color:var(--nav-item-text-muted)]">{subtitle}</span>
        </span>
      </Link>
      {onClose ? <button type="button" className="rounded-[5px] p-2 text-[color:var(--nav-item-text-muted)] hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--nav-item-text-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)] lg:hidden" aria-label="Close menu" onClick={onClose}><X size={15}/></button> : null}
    </div>
  );
}
