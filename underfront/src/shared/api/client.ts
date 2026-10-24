"use client";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

type Token = { access_token: string; expires_at: string };
const apiPrefix = "/v1";
const endpoint = (path: string) => path.startsWith(`${apiPrefix}/`) ? path : `${apiPrefix}${path}`;
let accessToken: string | null = null;
let expiresAt = 0;
let refreshPromise: Promise<string> | null = null;
const authLostListeners = new Set<() => void>();
export function onAuthLost(listener: () => void) {
  authLostListeners.add(listener);
  return () => { authLostListeners.delete(listener); };
}
const channel = typeof window === "undefined" || typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("puls-auth");
channel?.addEventListener("message", (event: MessageEvent<Token | { access_token: null }>) => {
  const value = event.data;
  if (value?.access_token) setAccessToken(value, false);
  else if (value?.access_token === null) clearAccessToken(false);
});

export function setAccessToken(value: Token, broadcast = true) {
  accessToken = value.access_token;
  expiresAt = Date.parse(value.expires_at);
  if (broadcast) channel?.postMessage(value);
}

export function clearAccessToken(broadcast = true) {
  accessToken = null;
  expiresAt = 0;
  if (broadcast) channel?.postMessage({ access_token: null });
  authLostListeners.forEach(listener => listener());
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body && typeof body === "object" ? body as { code?: string; message?: string } : null;
    throw new ApiError(response.status, error?.code ?? "http_error", error?.message ?? "API недоступен. Проверьте BACKEND_ORIGIN и работу Go-сервера.");
  }
  return body as T;
}

async function refreshToken(): Promise<string> {
  if (accessToken && expiresAt > Date.now() + 30_000) return accessToken;
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refresh = async () => {
        if (channel) await new Promise(resolve => window.setTimeout(resolve, 50));
        if (accessToken && expiresAt > Date.now() + 30_000) return accessToken;
        const response = await fetch(endpoint("/auth/refresh"), { method: "POST", credentials: "include", cache: "no-store" });
        let token: Token;
        try { token = await parseResponse<Token>(response); }
        catch (cause) {
          if (cause instanceof ApiError && cause.status === 401 && channel) {
            await new Promise(resolve => window.setTimeout(resolve, 120));
            if (accessToken && expiresAt > Date.now() + 30_000) return accessToken;
          }
          if (cause instanceof ApiError && cause.status === 401) clearAccessToken();
          throw cause;
        }
        setAccessToken(token);
        return token.access_token;
      };
      if (typeof navigator !== "undefined" && navigator.locks) return navigator.locks.request("puls-auth-refresh", refresh);
      return refresh();
    })().finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const send = async (token?: string) => {
    const headers = new Headers(init.headers);
    if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(endpoint(path), { ...init, headers, credentials: "include", cache: init.cache ?? "no-store" });
  };
  let token: string | undefined;
  if (authenticated) token = await refreshToken();
  let response = await send(token);
  if (authenticated && response.status === 401) {
    accessToken = null;
    expiresAt = 0;
    token = await refreshToken();
    response = await send(token);
    if (response.status === 401) clearAccessToken();
  }
  return parseResponse<T>(response);
}

export async function login(email: string, password: string) {
  const token = await apiRequest<Token>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }, false);
  setAccessToken(token);
}

export async function register(email: string, password: string) {
  const token = await apiRequest<Token>("/auth/register", { method: "POST", body: JSON.stringify({ email, password, consent_pd: true }) }, false);
  setAccessToken(token);
}

export async function logout() {
  await apiRequest<void>("/auth/logout", { method: "POST" });
  clearAccessToken();
}
