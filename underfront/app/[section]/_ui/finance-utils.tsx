"use client";
import { useEffect, useRef, useState } from "react";
import { api, message, type Job } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, ErrorState } from "@/src/shared/ui";
import { rubles } from "@/src/entities/forecast";

export const money = (value: number | null | undefined) => value == null ? "Нет данных" : rubles(value);
export const percent = (value: number | null | undefined) => value == null ? "Недостаточно данных" : `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
export const today = () => new Date().toLocaleDateString("sv-SE");
export const linkClass = "text-[color:var(--accent)] underline underline-offset-4";
export const fieldGrid = "grid gap-3 sm:grid-cols-2";
export const taxOptions = [{ value: "unknown", label: "Не указан" }, { value: "usn6", label: "УСН — доходы" }, { value: "usn15", label: "УСН — доходы минус расходы" }, { value: "osno", label: "Общая система" }, { value: "eshn", label: "ЕСХН" }];
export const directions = [{ value: "in", label: "Поступление" }, { value: "out", label: "Списание" }];
export const eventStatuses = [{ value: "expected", label: "Ожидается" }, { value: "received", label: "Оплачен" }, { value: "missed", label: "Просрочен" }, { value: "cancelled", label: "Отменён" }];
const statusLabels: Record<string, string> = { expected: "Ожидается", received: "Оплачен", missed: "Просрочен", cancelled: "Отменён", open: "Открыт", partial: "Частично оплачен", paid: "Оплачен", overdue: "Просрочен", ok: "Готово", error: "Ошибка", active: "Активен", blocked: "Заблокирован", new: "Новый", in_progress: "На проверке", closed: "Закрыт", queued: "В очереди", running: "Обрабатывается", done: "Готово", failed: "Ошибка" };
export const statusLabel = (value: string) => statusLabels[value] ?? value;

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const active = useRef(true);
  const locked = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function run<T>(work: () => Promise<T>, onSuccess?: (value: T) => void, success = "Изменения сохранены.") {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null); setNotice(null);
    try { const result = await work(); if (active.current) { onSuccess?.(result); setNotice(success); } }
    catch (cause) { if (active.current) setError(message(cause)); }
    finally { locked.current = false; if (active.current) setBusy(false); }
  }
  return { busy, error, notice, run, setError, setNotice };
}
export function ActionFeedback({ action }: { action: ReturnType<typeof useAction> }) {
  return <>{action.error && <ErrorState description={action.error} action={<Button variant="outline" onClick={() => api.invalidate()}>Обновить данные</Button>} />}{action.notice && <p role="status" className="text-sm text-[color:var(--text-secondary)]">{action.notice}</p>}</>;
}
export function JobProgress({ initial, download = false, onFinished }: { initial: Job; download?: boolean; onFinished?: (job: Job) => void }) {
  const resource = useApiResource<Job>(`/v1/jobs/${encodeURIComponent(initial.id)}`);
  const job = resource.data ?? initial;
  const action = useAction();
  const finished = job.status === "done" || job.status === "failed";
  const refresh = resource.refresh;
  useEffect(() => {
    if (finished || resource.loading || resource.error) return;
    const timer = setTimeout(refresh, 1500);
    return () => clearTimeout(timer);
  }, [job, finished, resource.loading, resource.error, refresh]);
  const finishCallback = useRef(onFinished);
  useEffect(() => { finishCallback.current = onFinished; }, [onFinished]);
  const notified = useRef(false);
  useEffect(() => { if (finished && !notified.current) { notified.current = true; api.invalidate(); finishCallback.current?.(job); } }, [finished, job]);
  return <div className="space-y-2 rounded-md border border-[color:var(--border)] p-4 text-sm"><p role="status">{statusLabel(job.status)} · {Math.round(job.progress * 100)}%</p>{job.error && <p role="alert">{job.error}</p>}{resource.error && <ErrorState description={resource.error} action={<Button onClick={resource.refresh}>Продолжить проверку</Button>} />}{download && job.status === "done" && <Button loading={action.busy} onClick={() => void action.run(async () => saveBlob(await api.download(`/v1/jobs/${job.id}/download`), "company-export.zip"), undefined, "Файл скачан.")}>Скачать архив</Button>}<ActionFeedback action={action} /></div>;
}
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
