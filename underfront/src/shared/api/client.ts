import type { components } from "./schema.gen";

export type Schemas = components["schemas"];
export type Company = Schemas["Company"];
export type Forecast = Schemas["Forecast"];
export type PlannedEvent = Schemas["PlannedEvent"];
export type Gap = Schemas["Gap"];
export type Job = Schemas["Job"];

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
  private listeners = new Set<() => void>();
  constructor(
    origin = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080",
    private transport: typeof fetch = (...args) => fetch(...args),
  ) {
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
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }
  private lost() {
    this.token = null;
    this.listeners.forEach((listener) => listener());
  }
  private async send(
    path: string,
    options: Options,
    retry = true,
  ): Promise<Response> {
    if (!path.startsWith("/v1/") || path.includes("\\"))
      throw new Error("Expected a relative /v1/ API path");
    const authenticated = options.authenticated !== false;
    if (authenticated && !this.token) await this.refresh();
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
    if (response.status === 401 && authenticated && retry) {
      // Another request may already have rotated the token while this one was in flight.
      if (headers.get("Authorization") === `Bearer ${this.token}`)
        await this.refresh();
      return this.send(path, options, false);
    }
    if (!response.ok) {
      if (response.status === 401 && authenticated) this.lost();
      const payload = await response.json().catch(() => ({}));
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
    const response = await this.send(path, options);
    if (response.status === 204) return undefined as T;
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError(
        502,
        "invalid_response",
        "Сервер вернул ответ неизвестного формата.",
      );
    }
  }
  refresh(): Promise<void> {
    if (!this.refreshing) {
      const generation = this.generation;
      const refresh = async () => {
        try {
          const token = await this.request<Schemas["Token"]>(
            "/v1/auth/refresh",
            { method: "POST", authenticated: false },
          );
          if (generation !== this.generation)
            throw new ApiError(401, "session_changed", "Сессия завершена.");
          this.token = token.access_token;
        } catch (error) {
          if (generation === this.generation) this.lost();
          throw error;
        }
      };
      // Rotation is serialized across tabs sharing the same refresh cookie.
      this.refreshing = (async () => {
        if (typeof navigator !== "undefined" && navigator.locks)
          await navigator.locks.request(`puls-refresh:${this.origin}`, refresh);
        else await refresh();
      })().finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }
  async authenticate(
    mode: "login" | "register",
    email: string,
    password: string,
    consent = false,
  ) {
    const token = await this.request<Schemas["Token"]>(`/v1/auth/${mode}`, {
      method: "POST",
      authenticated: false,
      json: {
        email,
        password,
        ...(mode === "register" ? { consent_pd: consent } : {}),
      },
    });
    this.generation++;
    this.token = token.access_token;
    return this.me();
  }
  me() {
    return this.request<Schemas["Profile"]>("/v1/me");
  }
  async logout() {
    this.generation++;
    await this.request<void>("/v1/auth/logout", { method: "POST" });
    this.generation++;
    this.lost();
  }
  createCompany(input: Schemas["CompanyCreate"]) {
    return this.request<Company>("/v1/companies", {
      method: "POST",
      json: input,
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
      if (job.status === "done") return job;
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
    return (await this.send(path, { signal })).blob();
  }
}

export const api = new ApiClient();
export function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Не удалось выполнить действие.";
}
