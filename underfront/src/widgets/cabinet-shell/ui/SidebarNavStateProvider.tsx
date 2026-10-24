"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type SidebarNavState = {
  expandedSections: string[] | null;
  openSection: (section: string) => void;
  toggleSection: (section: string, initialSections: string[]) => void;
};

const SidebarNavStateContext = createContext<SidebarNavState | null>(null);

/** Keeps the sidebar's expanded groups mounted across page navigation. */
export function SidebarNavStateProvider({ children }: { children: ReactNode }) {
  const [expandedSections, setExpandedSections] = useState<string[] | null>(null);

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
