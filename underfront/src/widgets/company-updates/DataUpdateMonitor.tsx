"use client";
import { useEffect, useState } from "react";
import { useSession } from "@/src/features/auth";
import { api, type Schemas } from "@/src/shared/api";

export function DataUpdateMonitor() {
  const { company, reload } = useSession();
  const cid = company?.id;
  const [state, setState] = useState<{
    cid: string;
    pending: boolean;
    error: string | null;
  } | null>(null);
  useEffect(() => {
    if (!cid) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let fingerprint: string | null = null;
    let revision: number | null = null;
    let running = false;
    const poll = async () => {
      if (running || controller.signal.aborted) return;
      running = true;
      try {
        if (document.visibilityState === "hidden") return;
        const update = await api.request<Schemas["CompanyUpdates"]>(
          `/v1/companies/${cid}/updates`,
          { signal: controller.signal },
        );
        if (controller.signal.aborted) return;
        const next = JSON.stringify(update);
        if (next !== fingerprint) {
          api.invalidate();
          if (revision !== null && revision !== update.data_revision)
            void reload().catch(() => {});
        }
        fingerprint = next;
        revision = update.data_revision;
        setState({
          cid,
          pending: update.pending_jobs > 0,
          error: update.last_job_error,
        });
      } catch (e) {
        if (!controller.signal.aborted)
          setState({
            cid,
            pending: false,
            error:
              e instanceof Error
                ? e.message
                : "Не удалось проверить обновления",
          });
      } finally {
        running = false;
        if (!controller.signal.aborted) timer = setTimeout(poll, 5000);
      }
    };
    const resume = () => {
      if (document.visibilityState === "visible" && !running) {
        clearTimeout(timer);
        void poll();
      }
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("focus", resume);
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("focus", resume);
    };
  }, [cid, reload]);
  if (state?.cid !== cid || (!state?.pending && !state?.error)) return null;
  return (
    <div
      role="status"
      className="border-b border-[color:var(--border)] bg-[color:var(--surface-subtle)] px-4 py-2 text-xs text-[color:var(--text-secondary)]"
    >
      {state.pending
        ? "Обрабатываем новые данные. Прогноз и план-факт обновятся автоматически."
        : `Последнее обновление: ${state.error}`}
    </div>
  );
}
