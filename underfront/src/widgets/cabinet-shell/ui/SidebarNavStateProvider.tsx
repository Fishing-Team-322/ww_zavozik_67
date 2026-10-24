"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

type SidebarNavState = {
  expandedSections: string[] | null;
  openSection: (section: string) => void;
  toggleSection: (section: string, initialSections: string[]) => void;
};

const SidebarNavStateContext = createContext<SidebarNavState | null>(null);
const storageKey = "puls-sidebar-expanded-sections";

/** Keeps the sidebar's expanded groups mounted across page navigation. */
export function SidebarNavStateProvider({ children }: { children: ReactNode }) {
  const [expandedSections, setExpandedSections] = useState<string[] | null>(null);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
        if (Array.isArray(saved) && saved.every((section) => typeof section === "string")) {
          setExpandedSections((current) => [...new Set([...(current ?? []), ...saved])]);
        }
      } catch {}
      setRestored(true);
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!restored || expandedSections === null) return;
    try { sessionStorage.setItem(storageKey, JSON.stringify(expandedSections)); } catch {}
  }, [expandedSections, restored]);

  const openSection = useCallback((section: string) => {
    setExpandedSections((current) => {
      if (current?.includes(section)) return current;
      return [...(current ?? []), section];
    });
  }, []);

  const toggleSection = useCallback((section: string, initialSections: string[]) => {
    setExpandedSections((current) => {
      const expanded = current ?? initialSections;
      return expanded.includes(section)
        ? expanded.filter((item) => item !== section)
        : [...expanded, section];
    });
  }, []);

  return (
    <SidebarNavStateContext.Provider value={{ expandedSections, openSection, toggleSection }}>
      {children}
    </SidebarNavStateContext.Provider>
  );
}

export function useSidebarNavState() {
  const state = useContext(SidebarNavStateContext);
  if (!state) throw new Error("SidebarNav must be rendered inside SidebarNavStateProvider");
  return state;
}
