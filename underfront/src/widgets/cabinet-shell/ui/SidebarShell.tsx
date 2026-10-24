"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { CircleHelp, Folder, Menu, Moon, Sun } from "lucide-react";
import CompanyIdenticonAvatar from "@/src/shared/ui/AbstractAvatar/AbstractAvatar";
import { Breadcrumbs, type BreadcrumbItem } from "@/src/shared/ui/breadcrumbs/breadcrumbs";
import { Button } from "@/src/shared/ui/button";
import { Select, type SelectOption } from "@/src/shared/ui/select";
import { SidebarBrand, SidebarNav, SidebarUtilityNav, type SidebarNavItem, defaultCabinetNav, sidebarSectionIcons } from "./SidebarNav";

const mockOrganizationOptions: SelectOption[] = [
  { value: "huy", label: "ООО Хуйня" },
  { value: "cats", label: "ООО Котики" },
  { value: "zero", label: "ООО Нолик" },
  { value: "change", label: "ООО Ой всё" },
];

export type SidebarShellProps = {
  children: ReactNode;
  navItems?: SidebarNavItem[];
  appTitle?: string;
  appSubtitle?: string;
  organizationName?: string;
  userName?: string;
  sidebarFooter?: ReactNode;
  /** Kept for existing callers; rendered in the sidebar footer. */
  topRight?: ReactNode;
};

function breadcrumbsForPath(pathname: string, navItems: SidebarNavItem[]): BreadcrumbItem[] {
  const path = pathname.replace(/\/+$/, "") || "/";
  const page = navItems
    .filter((item) => item.href === path || (item.href !== "/" && path.startsWith(`${item.href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];

  if (!page) return [
    { label: "Navigation", icon: Folder },
    { label: "Page not found", icon: CircleHelp },
  ];

  const section = page.section ?? "Navigation";
  const sectionIcon = sidebarSectionIcons[section] ?? Folder;
  const nestedSegments = path === page.href ? [] : path.slice(page.href.length).split("/").filter(Boolean);
  const items: BreadcrumbItem[] = [
    { label: section, icon: sectionIcon },
    { label: page.label, icon: page.icon ?? Folder, href: nestedSegments.length ? page.href : undefined },
  ];

  let href = page.href;
  nestedSegments.forEach((segment, index) => {
    href += `/${segment}`;
    items.push({
      label: decodeURIComponent(segment).replace(/[-_]/g, " "),
      icon: Folder,
      href: index < nestedSegments.length - 1 ? href : undefined,
    });
  });

  return items;
}

/** Cabinet shell with shared desktop and mobile navigation. */
export function SidebarShell({children, navItems = defaultCabinetNav, appTitle = "PULSE", appSubtitle = "Financial radar", organizationName = "ПУЛЬС", userName = "Пользователь", sidebarFooter, topRight}: SidebarShellProps) {
  const pathname = usePathname() || "/";
  const [mobileOpen, setMobileOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const profileRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = document.documentElement.getAttribute("data-theme");
    if (saved === "light" || saved === "dark") setTheme(saved);
  }, []);
  useEffect(() => {
    if (!mobileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileOpen]);
  useEffect(() => {
    if (!profileOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (!profileRef.current?.contains(event.target as Node)) setProfileOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setProfileOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [profileOpen]);
  function toggleTheme() {
    const next = theme === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("puls-theme", next); } catch {}
    setTheme(next);
  }

  const side = (close?: () => void) => (
    <div className="flex h-full min-h-0 flex-col pt-3 lg:pt-4">
      {close ? <SidebarBrand title={appTitle} subtitle={appSubtitle} onClose={close} /> : null}
      <SidebarNav items={navItems} onNavigate={close} />
      <div className="shrink-0 space-y-0.5 border-t border-[color:var(--border)] px-3 pb-3 pt-2">
        <SidebarUtilityNav item={navItems.find((item) => item.href === "/sources")} onNavigate={close} />
        {(sidebarFooter ?? topRight) ? <div className="py-1">{sidebarFooter ?? topRight}</div> : null}
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Light theme" : "Dark theme"}
          className="flex h-8 w-full items-center gap-2 rounded-[5px] px-2 text-left text-sm font-medium leading-4 tracking-normal tabular-nums text-[color:var(--nav-item-text)] transition-colors hover:bg-[color:var(--nav-item-hover-bg)] hover:text-[color:var(--nav-item-text-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[color:var(--nav-focus-ring)]"
        >
          {theme === "dark" ? <Sun size={15} className="shrink-0 text-[color:var(--nav-item-icon)]" aria-hidden="true" /> : <Moon size={15} className="shrink-0 text-[color:var(--nav-item-icon)]" aria-hidden="true" />}
          <span>{theme === "dark" ? "Light theme" : "Dark theme"}</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen text-[var(--text-primary)] lg:grid lg:grid-cols-[232px_minmax(0,1fr)] lg:grid-rows-[48px_minmax(0,1fr)]">
      <header className="sticky top-0 z-30 flex h-12 items-center justify-between gap-2 border-b border-[color:var(--border)] bg-[color:var(--chrome-bg)] pl-3 pr-4 sm:pr-5 xl:pr-7 lg:col-span-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <button
            type="button"
            aria-label="Collapse sidebar"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[5px] text-[color:var(--nav-item-icon-active)] transition-colors hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--nav-item-text-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="3" width="18" height="18" rx="2.5" />
              <path d="M9 3v18M16 9l-3 3 3 3" />
            </svg>
          </button>
          <div className="min-w-0 max-w-full">
            <Select size="md" fitContent aria-label="Организация" options={mockOrganizationOptions} defaultValue="huy" />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="hidden items-center gap-4 sm:flex">
            <span className="whitespace-nowrap text-[12px] font-medium leading-4 tracking-normal tabular-nums text-[color:var(--nav-item-text)]">Обновлено сегодня, 09:40</span>
            <Button type="button" variant="outline" size="md">
              <span className="">+ Событие</span>
            </Button>
          </div>
          <div
            ref={profileRef}
            className="relative"
            onPointerEnter={(event) => { if (event.pointerType === "mouse") setProfileOpen(true); }}
            onPointerLeave={(event) => { if (event.pointerType === "mouse") setProfileOpen(false); }}
            onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setProfileOpen(false); }}
          >
            <button
              type="button"
              aria-label="Профиль пользователя"
              aria-controls="header-profile-popover"
              aria-expanded={profileOpen}
              onFocus={() => setProfileOpen(true)}
              onClick={() => setProfileOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]"
            >
              <CompanyIdenticonAvatar seed={organizationName} size={32} rounded={16} className="h-8 w-8" />
            </button>
            {profileOpen ? (
              <div id="header-profile-popover" className="absolute right-0 top-full z-50 w-60 pt-2">
                <div className="rounded-md border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-4 shadow-[var(--shadow-md)]">
                  <p className="text-xs font-medium text-[color:var(--text-secondary)]">Профиль</p>
                  <p className="mt-1 truncate text-sm font-semibold text-[color:var(--text-primary)]">{userName}</p>
                  <p className="mt-1 truncate text-xs text-[color:var(--text-secondary)]">{organizationName}</p>
                </div>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            aria-label="Open menu"
            aria-controls="mobile-navigation"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
            className="rounded-[5px] p-2 text-[color:var(--nav-item-icon)] hover:bg-[color:var(--sidebar-hover)] hover:text-[color:var(--nav-item-text-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--nav-focus-ring)] lg:hidden"
          >
            <Menu size={20} aria-hidden="true" />
          </button>
        </div>
      </header>
      <aside className="sticky top-12 hidden h-[calc(100vh-48px)] min-h-0 border-r border-[color:var(--border)] bg-[color:var(--sidebar-bg)] lg:block">{side()}</aside>
      <main id="main-content" className="min-h-[calc(100vh-48px)] min-w-0 bg-[color:var(--surface)] p-4 sm:p-6">
        <div className="space-y-6">
          <Breadcrumbs items={breadcrumbsForPath(pathname, navItems)} />
          {children}
        </div>
      </main>
      {mobileOpen ? <>
        <button type="button" aria-label="Close menu" onClick={() => setMobileOpen(false)} className="fixed inset-0 z-40 bg-[color:var(--page-bg)] lg:hidden" />
        <aside id="mobile-navigation" aria-label="Mobile navigation" className="fixed inset-y-0 left-0 z-50 w-[232px] max-w-[86vw] border-r border-[color:var(--border)] bg-[color:var(--sidebar-bg)] lg:hidden">{side(() => setMobileOpen(false))}</aside>
      </> : null}
    </div>
  );
}
