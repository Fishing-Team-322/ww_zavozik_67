"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, login, logout, onAuthLost, register } from "@/src/shared/api/client";
import { authApi } from "../api/auth-api";
import type { AuthStatus, AuthUser } from "./types";

type AuthContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  error: string | null;
  sessionExpired: boolean;
  refreshProfile: () => Promise<AuthUser>;
  signIn: (email: string, password: string) => Promise<AuthUser>;
  signUp: (email: string, password: string) => Promise<AuthUser>;
  signOut: () => Promise<void>;
  retry: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const hadSession = useRef(false);

  const refreshProfile = useCallback(async () => {
    try {
      const profile = await authApi.me();
      setUser(profile);
      hadSession.current = true;
      setStatus("authenticated");
      setError(null);
      setSessionExpired(false);
      return profile;
    } catch (cause) {
      setUser(null);
      if (cause instanceof ApiError && cause.status === 401) {
        setStatus("guest");
        setError(null);
        setSessionExpired(current => current || hadSession.current);
        hadSession.current = false;
      } else {
        setStatus("error");
        setError(cause instanceof TypeError ? "Не удалось подключиться к серверу. Проверьте его доступность." : cause instanceof Error ? cause.message : "Сервер недоступен");
      }
      throw cause;
    }
  }, []);

  useEffect(() => {
    void refreshProfile().catch(() => {});
  }, [refreshProfile]);

  useEffect(() => onAuthLost(() => {
    setSessionExpired(hadSession.current);
    hadSession.current = false;
    setUser(null);
    setStatus("guest");
    setError(null);
  }), []);

  const signIn = useCallback(async (email: string, password: string) => {
    await login(email, password);
    return refreshProfile();
  }, [refreshProfile]);
  const signUp = useCallback(async (email: string, password: string) => {
    await register(email, password);
    return refreshProfile();
  }, [refreshProfile]);
  const signOut = useCallback(async () => {
    try { await logout(); }
    catch (cause) {
      if (!(cause instanceof ApiError && cause.status === 401)) throw cause;
    }
    setUser(null);
    setStatus("guest");
    setError(null);
    setSessionExpired(false);
  }, []);
  const retry = useCallback(async () => {
    setStatus("loading");
    try { await refreshProfile(); } catch { /* Status and error are set by refreshProfile. */ }
  }, [refreshProfile]);

  const value = useMemo(() => ({ user, status, error, sessionExpired, refreshProfile, signIn, signUp, signOut, retry }), [user, status, error, sessionExpired, refreshProfile, signIn, signUp, signOut, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
