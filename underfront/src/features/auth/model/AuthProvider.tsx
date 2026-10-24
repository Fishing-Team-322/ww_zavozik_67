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
  logoutWarning: string | null;
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
  const [logoutWarning, setLogoutWarning] = useState<string | null>(null);
  const hadSession = useRef(false);
  const profileRevision = useRef(0);

  const refreshProfile = useCallback(async () => {
    const revision = ++profileRevision.current;
    try {
      const profile = await authApi.me();
      if (revision !== profileRevision.current) throw new ApiError(401, "session_changed", "Сессия изменилась.");
      setUser(profile);
      hadSession.current = true;
      setStatus("authenticated");
      setError(null);
      setSessionExpired(false);
      return profile;
    } catch (cause) {
      if (revision !== profileRevision.current) throw cause;
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
    profileRevision.current++;
    const expired = hadSession.current;
    setSessionExpired(current => current || expired);
    hadSession.current = false;
    setUser(null);
    setStatus("guest");
    setError(null);
  }), []);

  const authenticate = useCallback(async (action: () => Promise<AuthUser>) => {
    // The client invalidates the old session synchronously before sending credentials.
    const pending = action();
    const revision = ++profileRevision.current;
    setUser(null);
    setStatus("loading");
    setError(null);
    setSessionExpired(false);
    setLogoutWarning(null);
    try {
      const profile = await pending;
      if (revision !== profileRevision.current) throw new ApiError(401, "session_changed", "Вход отменён.");
      setUser(profile);
      hadSession.current = true;
      setStatus("authenticated");
      return profile;
    } catch (cause) {
      if (revision === profileRevision.current) setStatus("guest");
      throw cause;
    }
  }, []);
  const signIn = useCallback((email: string, password: string) => authenticate(() => login(email, password)), [authenticate]);
  const signUp = useCallback((email: string, password: string) => authenticate(() => register(email, password)), [authenticate]);
  const signOut = useCallback(async () => {
    const pending = logout();
    const revision = ++profileRevision.current;
    hadSession.current = false;
    setUser(null);
    setStatus("guest");
    setError(null);
    setSessionExpired(false);
    setLogoutWarning(null);
    try { await pending; }
    catch {
      if (revision === profileRevision.current)
        setLogoutWarning("Вы вышли на этом устройстве. Сервер не подтвердил завершение сессии.");
    }
  }, []);
  const retry = useCallback(async () => {
    setStatus("loading");
    try { await refreshProfile(); } catch { /* Status and error are set by refreshProfile. */ }
  }, [refreshProfile]);

  const value = useMemo(() => ({ user, status, error, sessionExpired, logoutWarning, refreshProfile, signIn, signUp, signOut, retry }), [user, status, error, sessionExpired, logoutWarning, refreshProfile, signIn, signUp, signOut, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
