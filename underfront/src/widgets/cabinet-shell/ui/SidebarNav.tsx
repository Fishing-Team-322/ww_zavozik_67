"use client";

import { forwardRef, useId, useLayoutEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon, LucideProps } from "lucide-react";
import { Activity, ChevronDown, FileSpreadsheet, FlaskConical, LayoutGrid, SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/src/shared/lib/cn";
import { useSidebarNavState } from "./SidebarNavStateProvider";

/** A small, application-independent replacement for the old role-based navigation. */
export type SidebarNavItem = {
  href: string;
  label: string;
  icon?: LucideIcon;
  section?: string;
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
const AnalyticsIcon = createFilledIcon("AnalyticsIcon", "M8 21H3V13H8V21ZM14.5 21H9.5V15H14.5V21ZM21 21H16V17H21V21ZM14.5 14H9.5V3H14.5V14ZM21 16H16V8H21V16ZM8 12H3V8H8V12Z");
const PlanningIcon = createFilledIcon("PlanningIcon", "M10 10.1111V1L21 7V21H3V7L10 10.1111Z");
const TransactionsIcon = createFilledIcon("TransactionsIcon", "M9.3349 11.5023L11.5049 11.5028C13.9902 11.5028 16.0049 13.5175 16.0049 16.0028H9.00388L9.00488 17.0028L17.0049 17.002V16.0028C17.0049 14.9204 16.6867 13.8997 16.1188 13.002L19.0049 13.0028C20.9972 13.0028 22.7173 14.1681 23.521 15.8542C21.1562 18.9748 17.3268 21.0028 13.0049 21.0028C10.2436 21.0028 7.90445 20.4122 6.00456 19.378L6.00592 10.0738C7.25147 10.2522 8.39122 10.7585 9.3349 11.5023ZM5.00488 19.0028C5.00488 19.5551 4.55717 20.0028 4.00488 20.0028H2.00488C1.4526 20.0028 1.00488 19.5551 1.00488 19.0028V10.0028C1.00488 9.45052 1.4526 9.00281 2.00488 9.00281H4.00488C4.55717 9.00281 5.00488 9.45052 5.00488 10.0028V19.0028ZM18.0049 5.00281C19.6617 5.00281 21.0049 6.34595 21.0049 8.00281C21.0049 9.65966 19.6617 11.0028 18.0049 11.0028C16.348 11.0028 15.0049 9.65966 15.0049 8.00281C15.0049 6.34595 16.348 5.00281 18.0049 5.00281ZM11.0049 2.00281C12.6617 2.00281 14.0049 3.34595 14.0049 5.00281C14.0049 6.65966 12.6617 8.00281 11.0049 8.00281C9.34803 8.00281 8.00488 6.65966 8.00488 5.00281C8.00488 3.34595 9.34803 2.00281 11.0049 2.00281Z");
const ForecastIcon = createFilledIcon("ForecastIcon", "M3 3H21C21.5523 3 22 3.44772 22 4V20C22 20.5523 21.5523 21 21 21H3C2.44772 21 2 20.5523 2 20V4C2 3.44772 2.44772 3 3 3ZM7 13V17H9V13H7ZM11 7V17H13V7H11ZM15 10V17H17V10H15Z");
const CashShortfallsIcon = createFilledIcon("CashShortfallsIcon", "M1 5C1 4.44772 1.44772 4 2 4H22C22.5523 4 23 4.44772 23 5V19C23 19.5523 22.5523 20 22 20H2C1.44772 20 1 19.5523 1 19V5ZM9 8H7V10H9V8ZM7 13V16H9V11H6V13H7ZM13 9V11H19V9H13ZM18 13H13V15H18V13Z");
const PaymentCalendarIcon = createFilledIcon("PaymentCalendarIcon", "M17 3H21C21.5523 3 22 3.44772 22 4V20C22 20.5523 21.5523 21 21 21H3C2.44772 21 2 20.5523 2 20V4C2 3.44772 2.44772 3 3 3H7V1H9V3H15V1H17V3ZM4 9V19H20V9H4ZM6 11H8V13H6V11ZM6 15H8V17H6V15ZM10 11H18V13H10V11ZM10 15H15V17H10V15Z");

export const sidebarSectionIcons: Record<string, LucideIcon> = {
  Workspace: WorkspaceIcon,
  Analytics: AnalyticsIcon,
  Planning: PlanningIcon,
};

export const defaultCabinetNav: SidebarNavItem[] = [
  { href: "/overview", label: "Overview", icon: OverviewHomeIcon, section: "Workspace" },
  { href: "/transactions", label: "Transactions", icon: TransactionsIcon, section: "Workspace" },
  { href: "/forecast", label: "Forecast", icon: ForecastIcon, section: "Analytics" },
  { href: "/scenarios", label: "Scenarios", icon: SlidersHorizontal, section: "Analytics" },
  { href: "/risks", label: "Cash shortfalls", icon: CashShortfallsIcon, section: "Analytics" },
  { href: "/calendar", label: "Payment calendar", icon: PaymentCalendarIcon, section: "Planning" },
  { href: "/sources", label: "Data sources", icon: FileSpreadsheet, section: "Planning" },
  { href: "/development/components", label: "Buttons and fields", icon: LayoutGrid, section: "Development" },
  { href: "/test", label: "Payment calendar demo", icon: FlaskConical, section: "Development" },
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
  const mainItems = items.filter((item) => item.href !== "/sources" && item.section !== "Development" && item.section !== "Разработка");
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
