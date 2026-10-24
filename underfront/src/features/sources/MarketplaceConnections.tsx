"use client";
import { useCallback, useEffect, useState } from "react";
import { api, message, type Schemas } from "@/src/shared/api";
import { Button, Input, Select } from "@/src/shared/ui";
type Entry = Record<string, unknown> & { id: string; provider: string; external_id: string; amount_kopecks: number; period_from: string; period_to: string; operation_date?: string; data_mode: string };
export function MarketplaceConnections({ companyId, onChanged }: { companyId: string; onChanged: () => void }) {
  const [kind, setKind] = useState("wb");
  const [key, setKey] = useState(""); const [clientId, setClientId] = useState("");
  const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  const [rows, setRows] = useState<Entry[]>([]); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const reload = useCallback(async () => setRows(await api.request<Entry[]>(`/v1/companies/${companyId}/marketplace-reports`)), [companyId]);
  useEffect(() => { const controller = new AbortController(); void api.request<Entry[]>(`/v1/companies/${companyId}/marketplace-reports`, { signal: controller.signal }).then(setRows).catch(cause => { if (!controller.signal.aborted) setError(message(cause)); }); return () => controller.abort(); }, [companyId]);
  async function connect(event: React.FormEvent) {
    event.preventDefault(); if (busy) return; setBusy(true); setError(""); setNotice("");
    try {
      const source = await api.request<Schemas["Source"]>(`/v1/companies/${companyId}/sources`, { method: "POST", json: { kind, title: kind === "wb" ? "Wildberries · отчёты продавца" : "Ozon · отчёты продавца", config: { api_key: key, ...(kind === "ozon" ? { client_id: clientId } : {}), from, to } } });
      setKey(""); onChanged();
      await api.testSource(source.id);
      const job = await api.syncSource(source.id); await api.waitForJob(job);
      await reload(); onChanged(); setNotice("Отчёт сохранён отдельно от банковских операций. Начисление не подтверждает поступление на расчётный счёт.");
    } catch (cause) { setError(message(cause)); onChanged(); } finally { setBusy(false); }
  }
  return <section className="min-w-0 space-y-4 rounded-md border border-[color:var(--border)] p-5">
    <h2 className="text-lg font-semibold">Маркетплейсы · отчёты продавца</h2>
    <p className="text-sm text-[color:var(--text-secondary)]">Продажи, возвраты и комиссии — учёт внутри площадки. Они не становятся банковским фактом или остатком и не добавляются в прогноз автоматически. Живая проверка требует вашего кабинета и ключей с правом чтения финансов. Адаптеры проверены на mock; ваш источник станет подключённым только после успешного запроса.</p>
    <form onSubmit={connect} className="grid gap-3 sm:grid-cols-2">
      <Select label="Маркетплейс" value={kind} onChange={event => { setKind(event.target.value); setKey(""); }} options={[{ value: "wb", label: "Wildberries" }, { value: "ozon", label: "Ozon" }]} />
      {kind === "ozon" && <Input label="Client ID Ozon" required value={clientId} onChange={event => setClientId(event.target.value)} />}
      <Input label="Ключ продавца маркетплейса" type="password" required value={key} autoComplete="off" onChange={event => setKey(event.target.value)} helperText="Передаётся только backend и хранится зашифрованным. В ответах ключ не возвращается." />
      <Input label="Отчёт с даты" type="date" required value={from} onChange={event => setFrom(event.target.value)} /><Input label="Отчёт по дату" type="date" required value={to} onChange={event => setTo(event.target.value)} />
      <Button type="submit" disabled={busy}>{busy ? "Проверяем и загружаем…" : "Подключить и загрузить отчёт"}</Button>
    </form>
    {error && <p role="alert" className="text-sm text-[color:var(--danger)]">{error}</p>}{notice && <p role="status" className="text-sm">{notice}</p>}
    <Button variant="outline" disabled={busy} onClick={() => void reload().catch(cause => setError(message(cause)))}>Обновить отчёты</Button>
    <p className="text-sm">Версий записей: {rows.length}. Повтор той же записи не создаёт новую версию; изменения сохраняются по содержимому.</p>
    <div className="max-h-96 overflow-auto">{rows.slice(0, 200).map(row => <article key={row.id} className="space-y-1 border-t border-[color:var(--border)] py-2 text-sm"><p>{row.provider === "wb" ? "Wildberries" : "Ozon"} · {row.external_id} · {row.operation_date || `${row.period_from} — ${row.period_to}`}</p><p>{(row.amount_kopecks / 100).toLocaleString("ru-RU", { style: "currency", currency: "RUB" })} · {row.data_mode === "mock" ? "ДЕМОНСТРАЦИЯ / MOCK" : "Ответ сервиса продавца"} · вне банковского факта</p><details><summary>Состав учётной записи и источник</summary><pre className="overflow-auto text-xs">{JSON.stringify(row, null, 2)}</pre></details></article>)}</div>
  </section>;
}
