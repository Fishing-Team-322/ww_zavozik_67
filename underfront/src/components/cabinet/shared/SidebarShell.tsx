"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, CircleHelp, Folder, Menu, Moon, Sun } from "lucide-react";
import CompanyIdenticonAvatar from "@/src/components/ui/AbstractAvatar/AbstractAvatar";
import { Breadcrumbs, type BreadcrumbItem } from "@/src/components/ui/breadcrumbs/breadcrumbs";
import { SidebarBrand, SidebarNav, type SidebarNavItem, defaultCabinetNav } from "./SidebarNav";

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
    { label: "Навигация", icon: Folder },
    { label: "Страница не найдена", icon: CircleHelp },
  ];

  const section = page.section ?? "Навигация";
  const sectionIcon = navItems.find((item) => (item.section ?? "Навигация") === section)?.icon ?? Folder;
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

/** Adapted from the original 256px cabinet SidebarShell; no auth, roles or backend required. */
export function SidebarShell({children, navItems = defaultCabinetNav, appTitle = "ПУЛЬС", appSubtitle = "Финансовый радар", organizationName = "ПУЛЬС", userName = "Пользователь", sidebarFooter, topRight}: SidebarShellProps) {
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
    <div className="flex h-full min-h-0 flex-col py-3 lg:py-5">
      {close ? <SidebarBrand title={appTitle} subtitle={appSubtitle} onClose={close} /> : null}
      <SidebarNav items={navItems} onNavigate={close} />
      <div className="space-y-3 px-4 pb-3">
        {sidebarFooter ?? topRight}
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          className="flex w-full items-center gap-3 rounded-[6px] px-2 py-2 text-left text-sm font-medium leading-4 tracking-normal tabular-nums text-[color:var(--text-secondary)] transition-colors hover:text-[color:var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)]"
        >
          {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
          <span>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen text-[var(--text-primary)] lg:grid lg:grid-cols-[256px_minmax(0,1fr)] lg:grid-rows-[48px_minmax(0,1fr)]">
      <header className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-[color:var(--border)] bg-[color:var(--chrome-bg)] px-4 sm:px-5 xl:px-7 lg:col-span-2">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="flex shrink-0 items-center gap-2.5 text-sm font-semibold text-[color:var(--text-primary)]">
            <span className="flex h-7 w-7 items-center justify-center rounded-[7px] bg-[image:var(--brand-gradient)] text-white"><Activity size={16} aria-hidden="true" /></span>
            <span>{appTitle}</span>
          </Link>
          <span className="hidden truncate text-xs text-[color:var(--text-secondary)] sm:block">{appSubtitle}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
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
            aria-label="Открыть меню"
            aria-controls="mobile-navigation"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
            className="rounded-[10px] p-2 text-[color:var(--text-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] lg:hidden"
          >
            <Menu size={20} aria-hidden="true" />
          </button>
        </div>
      </header>
      <aside className="sticky top-12 hidden h-[calc(100vh-48px)] min-h-0 border-r border-[color:var(--border)] bg-[color:var(--chrome-bg)] lg:block">{side()}</aside>
      <main id="main-content" className="min-h-[calc(100vh-48px)] min-w-0 bg-[color:var(--surface)] p-4 sm:p-6">
        <div className="space-y-6">
          <Breadcrumbs items={breadcrumbsForPath(pathname, navItems)} />
          {children}
        </div>
      </main>
      {mobileOpen ? <>
        <button type="button" aria-label="Закрыть меню" onClick={() => setMobileOpen(false)} className="fixed inset-0 z-40 bg-[color:var(--page-bg)] lg:hidden" />
        <aside id="mobile-navigation" aria-label="Мобильная навигация" className="fixed inset-y-0 left-0 z-50 w-[86%] max-w-xs border-r border-[color:var(--border)] bg-[color:var(--chrome-bg)] lg:hidden">{side(() => setMobileOpen(false))}</aside>
      </> : null}
    </div>
  );
}
