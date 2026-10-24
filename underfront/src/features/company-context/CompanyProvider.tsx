"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Company } from "@/src/entities/company";
import { useAuth } from "@/src/features/auth/model/AuthProvider";

type CompanyContextValue = {
  companies: Company[];
  companyId: string | null;
  selectedCompany: Company | null;
  status: "loading" | "ready" | "unauthorized" | "error";
  error: string | null;
  selectCompany: (id: string) => void;
  reloadCompanies: (preferId?: string) => Promise<void>;
};

const CompanyContext = createContext<CompanyContextValue | null>(null);
const storageKey = "puls-selected-company-id";

export function CompanyProvider({ children }: { children: ReactNode }) {
  const { user, status: authStatus, error, refreshProfile } = useAuth();
  const [savedId, setSavedId] = useState<string | null>(null);
  const companies = user?.companies ?? [];
  const companyId = companies.find(item => item.id === savedId)?.id ?? companies[0]?.id ?? null;
  const selectedCompany = companies.find(item => item.id === companyId) ?? null;

  useEffect(() => {
    try { setSavedId(localStorage.getItem(storageKey)); } catch { setSavedId(null); }
    const onStorage = (event: StorageEvent) => {
      if (event.key === storageKey) setSavedId(event.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated" || !companyId) return;
    try { localStorage.setItem(storageKey, companyId); } catch { /* Storage is optional. */ }
  }, [authStatus, companyId]);

  const selectCompany = useCallback((id: string) => {
    if (!companies.some(item => item.id === id)) return;
    setSavedId(id);
    try { localStorage.setItem(storageKey, id); } catch { /* Storage is optional. */ }
  }, [companies]);

  const reloadCompanies = useCallback(async (preferId?: string) => {
    if (preferId) setSavedId(preferId);
    await refreshProfile();
  }, [refreshProfile]);

  const status: CompanyContextValue["status"] = authStatus === "authenticated" ? "ready" : authStatus === "guest" ? "unauthorized" : authStatus;
  const value = useMemo(() => ({ companies, companyId, selectedCompany, status, error, selectCompany, reloadCompanies }), [companies, companyId, selectedCompany, status, error, selectCompany, reloadCompanies]);
  return <CompanyContext.Provider value={value}>{children}</CompanyContext.Provider>;
}

export function useCompany() {
  const context = useContext(CompanyContext);
  if (!context) throw new Error("CompanyProvider is missing");
  return context;
}
