"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  ApiError,
  message,
  type Schemas,
  type Company,
} from "@/src/shared/api";

type Session = {
  profile: Schemas["Profile"] | null;
  company: Company | null;
  loading: boolean;
  error: string | null;
  login: (
    mode: "login" | "register",
    email: string,
    password: string,
    consent?: boolean,
  ) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
  selectCompany: (id: string) => void;
  createCompany: (input: Schemas["CompanyCreate"]) => Promise<void>;
};
const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<Schemas["Profile"] | null>(null);
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const accept = useCallback((next: Schemas["Profile"]) => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(`puls-company:${next.id}`);
    } catch {}
    setProfile(next);
    setCompanyId(
      next.companies.find((c) => c.id === saved)?.id ||
        next.companies[0]?.id ||
        null,
    );
    setError(null);
  }, []);
  const reload = useCallback(async () => {
    accept(await api.me());
  }, [accept]);
  useEffect(() => {
    let active = true;
    const unsubscribe = api.onSessionLost(() => {
      if (active) {
        setProfile(null);
        setCompanyId(null);
      }
    });
    api
      .refresh()
      .then(() => api.me())
      .then((next) => {
        if (active) accept(next);
      })
      .catch((error) => {
        if (active && !(error instanceof ApiError && error.status === 401))
          setError(message(error));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [accept]);
  const selectCompany = (id: string) => {
    if (!profile?.companies.some((company) => company.id === id)) return;
    setCompanyId(id);
    try {
      localStorage.setItem(`puls-company:${profile.id}`, id);
    } catch {}
  };
  const value: Session = {
    profile,
    company: profile?.companies.find((c) => c.id === companyId) || null,
    loading,
    error,
    reload,
    selectCompany,
    login: async (mode, email, password, consent) => {
      accept(await api.authenticate(mode, email, password, consent));
    },
    logout: async () => {
      await api.logout();
    },
    createCompany: async (input) => {
      const company = await api.createCompany(input);
      const next = await api.me();
      accept(next);
      setCompanyId(company.id);
      try {
        localStorage.setItem(`puls-company:${next.id}`, company.id);
      } catch {}
    },
  };
  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}
export function useSession() {
  const session = useContext(SessionContext);
  if (!session) throw new Error("SessionProvider is required");
  return session;
}
