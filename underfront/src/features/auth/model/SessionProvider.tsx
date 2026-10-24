"use client";

import { useAuth } from "./AuthProvider";
import { useCompany } from "@/src/features/company-context/CompanyProvider";

/** Compatibility view for financial screens; auth and company each have one owner. */
export function useSession() {
  const auth = useAuth();
  const company = useCompany();
  return {
    profile: auth.user,
    company: company.selectedCompany,
    loading: auth.status === "loading",
    error: auth.error,
    reload: company.reloadCompanies,
    selectCompany: company.selectCompany,
    logout: auth.signOut,
  };
}
