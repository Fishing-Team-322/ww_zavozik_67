import type { components } from "./schema.gen";

export type Schemas = components["schemas"];
export type Company = Schemas["Company"];
export type Forecast = Schemas["Forecast"];
export type PlannedEvent = Schemas["PlannedEvent"];
export type Gap = Schemas["Gap"];
export type Job = Schemas["Job"];
export type Source = Schemas["Source"];
export type SourceTest = {
  ok: boolean;
  ready_to_sync: boolean;
  message: string;
  missing?: string[];
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
type Options = {
  method?: string;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  headers?: HeadersInit;
  authenticated?: boolean;
};

/** Browser access token is held in memory; refresh stays in the server's HttpOnly cookie. */
export class ApiClient {
  readonly origin: string;
  private token: string | null = null;
  private refreshing: Promise<void> | null = null;
  private generation = 0;
  private channel: BroadcastChannel | null = null;
  private sessionBlocked = false;
  private authQueue: Promise<unknown> = Promise.resolve();
  private get logoutKey() { return `puls-logged-out:${this.origin}`; }
  private isSessionBlocked() {
    try { return this.sessionBlocked || (typeof window !== "undefined" && localStorage.getItem(this.logoutKey) === "1"); }
    catch { return this.sessionBlocked; }
  }
  private blockSession(blocked: boolean) {
    this.sessionBlocked = blocked;
    // Only a logout flag is persisted, never credentials or profile data.
    try {
      if (blocked) localStorage.setItem(this.logoutKey, "1");
      else localStorage.removeItem(this.logoutKey);
    } catch { /* Storage may be disabled; the in-memory guard still applies. */ }
  }
  private assertSession(generation: number) {
    if (generation !== this.generation || this.isSessionBlocked())
      throw new ApiError(401, "session_changed", "Сессия завершена. Войдите снова.");
  }
  private serializeAuth<T>(action: () => Promise<T>): Promise<T> {
    const pending = this.authQueue.catch(() => {}).then(async () => {
      if (typeof navigator !== "undefined" && navigator.locks)
        return await navigator.locks.request<Promise<T>>(`puls-refresh:${this.origin}`, action);
      return await action();
    });
    this.authQueue = pending;
    return pending;
  }
  private observingSession = false;
  private ensureChannel() {
    if (this.observingSession || typeof window === "undefined") return;
    this.observingSession = true;
    window.addEventListener("storage", event => {
      if (event.key === this.logoutKey && event.newValue === "1") this.endLocalSession();
    });
    if (typeof BroadcastChannel === "undefined") return;
    this.channel = new BroadcastChannel(`puls-auth:${this.origin}`);
    this.channel.onmessage = event => { if (event.data === "logout") this.endLocalSession(); };
  }
  private dataListeners = new Set<() => void>();
  invalidate() { this.dataListeners.forEach(listener => listener()); }
  onDataChanged(listener: () => void) { this.dataListeners.add(listener); return () => { this.dataListeners.delete(listener); }; }
  private listeners = new Set<() => void>();
  constructor(
    origin = process.env.NEXT_PUBLIC_API_URL || "",
    private transport: typeof fetch = (...args) => fetch(...args),
  ) {
    if (!origin) { this.origin = ""; return; }
    const url = new URL(origin);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      url.pathname !== "/"
    )
      throw new Error("NEXT_PUBLIC_API_URL must be an HTTP(S) origin");
    this.origin = url.origin;
  }
  onSessionLost(listener: () => void) {
    this.ensureChannel();
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  clearSession() {
    this.blockSession(true);
    this.endLocalSession();
    this.channel?.postMessage("logout");
  }
  private endLocalSession() {
    this.sessionBlocked = true;
    this.generation++;
    this.token = null;
    this.refreshing = null;
    this.listeners.forEach((listener) => listener());
  }
  /** Called only by the explicit OAuth completion route. */
  allowSessionRestore() {
    this.endLocalSession();
    this.blockSession(false);
  }
  private async send(
    path: string,
    options: Options,
    retry = true,
  ): Promise<Response> {
    if (!path.startsWith("/v1/") || path.includes("\\"))
      throw new Error("Expected a relative /v1/ API path");
    const authenticated = options.authenticated !== false;
    const generation = this.generation;
    if (authenticated) this.assertSession(generation);
    if (authenticated && !this.token) await this.refresh();
    if (authenticated) this.assertSession(generation);
    options.signal?.throwIfAborted();
    const headers = new Headers(options.headers);
    if (authenticated && this.token)
      headers.set("Authorization", `Bearer ${this.token}`);
    if (options.json !== undefined)
      headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await this.transport(this.origin + path, {
        method: options.method || "GET",
        headers,
        body:
          options.form ||
          (options.json === undefined
            ? undefined
            : JSON.stringify(options.json)),
        signal: options.signal,
        credentials: "include",
        cache: "no-store",
        redirect: "error",
      });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      throw new ApiError(
        0,
        "network_unavailable",
        "Не удалось связаться с сервером. Проверьте соединение и повторите запрос.",
      );
    }
    if (authenticated) this.assertSession(generation);
    if (response.status === 401 && authenticated && retry) {
      // Another request may already have rotated the token while this one was in flight.
      if (headers.get("Authorization") === `Bearer ${this.token}`)
        await this.refresh();
      this.assertSession(generation);
      return this.send(path, options, false);
    }
    if (!response.ok) {
      if (response.status === 401 && authenticated) this.clearSession();
      const body: unknown = await response.json().catch(() => null);
      const payload = body !== null && typeof body === "object"
        ? body as Record<string, unknown>
        : {};
      throw new ApiError(
        response.status,
        typeof payload.code === "string" ? payload.code : "request_failed",
        typeof payload.message === "string"
          ? payload.message
          : "Сервер не смог выполнить запрос.",
      );
    }
    return response;
  }
  async request<T>(path: string, options: Options = {}): Promise<T> {
    const generation = this.generation;
    const response = await this.send(path, options);
    let result: T = undefined as T;
    if (response.status !== 204) {
      try { result = await response.json() as T; }
      catch {
        throw new ApiError(502, "invalid_response", "Сервер вернул ответ неизвестного формата.");
      }
    }
    // A body can finish downloading after logout or another account signs in.
    if (options.authenticated !== false) this.assertSession(generation);
    if (options.method && options.method !== "GET" && !/\/(preview|parse|simulate|test|refresh|login|register|logout)$/.test(path.split("?")[0])) this.invalidate();
    return result;
  }
  refresh(): Promise<void> {
    if (!this.refreshing) {
      const generation = this.generation;
      const pending: Promise<void> = this.serializeAuth(async () => {
        this.assertSession(generation);
        try {
          const token = await this.request<Schemas["Token"]>("/v1/auth/refresh", { method: "POST", authenticated: false, signal: AbortSignal.timeout(15_000) });
          this.assertSession(generation);
          this.token = token.access_token;
        } catch (error) {
          // Transport/server failures do not revoke a still-valid refresh cookie.
          // Keep the session recoverable; only an explicit 401 ends it.
          if (generation === this.generation && error instanceof ApiError && error.status === 401) this.clearSession();
          throw error;
        }
      }).finally(() => {
        if (this.refreshing === pending) this.refreshing = null;
      });
      this.refreshing = pending;
    }
    return this.refreshing;
  }
  async authenticate(
    mode: "login" | "register",
    email: string,
    password: string,
    consent = false,
  ) {
    this.clearSession();
    const generation = this.generation;
    await this.serializeAuth(async () => {
      if (generation !== this.generation) throw new ApiError(401, "session_changed", "Вход отменён.");
      const token = await this.request<Schemas["Token"]>(`/v1/auth/${mode}`, {
        method: "POST", authenticated: false, signal: AbortSignal.timeout(15_000),
        json: { email, password, ...(mode === "register" ? { consent_pd: consent } : {}) },
      });
      if (generation !== this.generation) throw new ApiError(401, "session_changed", "Вход отменён.");
      this.blockSession(false);
      this.token = token.access_token;
    });
    return this.me();
  }
  me() {
    return this.request<Schemas["Profile"]>("/v1/me");
  }
  async logout() {
    const token = this.token;
    // Hide local data immediately, even if the server is offline or never responds.
    this.clearSession();
    await this.serializeAuth(async () => {
      // Explicit credentials avoid implicit refresh and restoring the local session.
      const revoke = (accessToken: string | null) => this.request<void>("/v1/auth/logout", {
        method: "POST", authenticated: false, signal: AbortSignal.timeout(15_000),
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
      });
      try { await revoke(token); }
      catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) throw error;
        try {
          const refreshed = await this.request<Schemas["Token"]>("/v1/auth/refresh", { method: "POST", authenticated: false, signal: AbortSignal.timeout(15_000) });
          await revoke(refreshed.access_token);
        } catch (cause) {
          if (!(cause instanceof ApiError && cause.status === 401)) throw cause;
        }
      }
    });
  }
  createCompany(input: Schemas["CompanyCreate"]) {
    return this.request<Company>("/v1/companies", {
      method: "POST",
      json: input,
    });
  }
  updateCompany(id: string, input: Schemas["CompanyPatch"], signal?: AbortSignal) {
    return this.request<Company>(`/v1/companies/${encodeURIComponent(id)}`, {
      method: "PATCH", json: input, signal,
    });
  }
  createSource(company: string, input: Schemas["CreateSourceInput"], signal?: AbortSignal) {
    return this.request<Source>(
      `/v1/companies/${encodeURIComponent(company)}/sources`,
      { method: "POST", json: input, signal },
    );
  }
  testSource(id: string, signal?: AbortSignal) {
    return this.request<SourceTest>(`/v1/sources/${encodeURIComponent(id)}/test`, {
      method: "POST",
      signal,
    });
  }
  syncSource(id: string, signal?: AbortSignal) {
    return this.request<Job>(`/v1/sources/${encodeURIComponent(id)}/sync`, {
      method: "POST",
      signal,
    });
  }
  dashboard(company: string, signal?: AbortSignal) {
    return this.request<Schemas["Dashboard"]>(
      `/v1/companies/${encodeURIComponent(company)}/dashboard`,
      { signal },
    );
  }
  forecast(company: string, signal?: AbortSignal) {
    return this.request<Forecast>(
      `/v1/companies/${encodeURIComponent(company)}/forecast`,
      { signal },
    );
  }
  createEvent(company: string, input: Schemas["CreateEventInput"]) {
    return this.request<PlannedEvent>(
      `/v1/companies/${encodeURIComponent(company)}/events`,
      { method: "POST", json: input },
    );
  }
  updateEvent(id: string, input: Schemas["UpdateEventInput"]) {
    return this.request<PlannedEvent>(`/v1/events/${encodeURIComponent(id)}`, {
      method: "PATCH",
      json: input,
    });
  }
  deleteEvent(id: string) {
    return this.request<void>(`/v1/events/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  }
  upload(company: string, file: File, signal?: AbortSignal) {
    const form = new FormData();
    form.append("file", file);
    return this.request<Job | Schemas["UploadMappingResult"]>(
      `/v1/companies/${encodeURIComponent(company)}/uploads`,
      { method: "POST", form, signal },
    );
  }
  async waitForJob(job: Job, signal?: AbortSignal): Promise<Job> {
    const deadline = Date.now() + 120_000;
    for (;;) {
      signal?.throwIfAborted();
      if (job.status === "done") { this.invalidate(); return job; }
      if (job.status === "failed")
        throw new ApiError(
          409,
          "job_failed",
          job.error || "Не удалось обработать файл.",
        );
      if (Date.now() > deadline)
        throw new ApiError(
          408,
          "job_pending",
          "Обработка продолжается. Результат будет доступен в истории загрузок.",
        );
      await new Promise<void>((resolve, reject) => {
        const abort = () => {
          clearTimeout(timer);
          signal?.removeEventListener("abort", abort);
          reject(signal?.reason);
        };
        const timer = setTimeout(() => {
          signal?.removeEventListener("abort", abort);
          resolve();
        }, 750);
        signal?.addEventListener("abort", abort, { once: true });
      });
      job = await this.request<Job>(`/v1/jobs/${encodeURIComponent(job.id)}`, {
        signal,
      });
    }
  }
  async download(path: string, signal?: AbortSignal) {
    const generation = this.generation;
    const blob = await (await this.send(path, { signal })).blob();
    this.assertSession(generation);
    return blob;
  }
}

export const api = new ApiClient();
export function message(error: unknown) {
  if (error instanceof ApiError && error.status === 409) return `${error.message} Обновите данные и повторите действие.`;
  return error instanceof Error
    ? error.message
    : "Не удалось выполнить действие.";
}

// Compatibility exports share the same client and in-memory token as financial screens.
export function apiRequest<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const form = init.body instanceof FormData ? init.body : undefined;
  const json = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
  return api.request<T>(path.startsWith("/v1/") ? path : `/v1${path}`, {
    method: init.method, headers: init.headers, signal: init.signal ?? undefined,
    form, json, authenticated,
  });
}
export const onAuthLost = (listener: () => void) => api.onSessionLost(listener);
export const clearAccessToken = () => api.clearSession();
export const login = (email: string, password: string) => api.authenticate("login", email, password);
export const register = (email: string, password: string) => api.authenticate("register", email, password, true);
export const logout = () => api.logout();
