"use client";
import { useState } from "react";
import Link from "next/link";
import { Bell, AlertTriangle, CheckCircle2 } from "lucide-react";
import { useCompany } from "@/src/features/company-context/CompanyProvider";
import { api, message, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Select, EmptyState, ErrorState } from "@/src/shared/ui";

export function alertLink(ref: Schemas["Alert"]["ref"]) {
  const id = encodeURIComponent(ref.id ?? "");
  if (ref.screen === "gap" && id) return `/risks?gap=${id}`;
  if (ref.screen === "event" && id) return `/calendar?event=${id}`;
  if (ref.screen === "counterparty" && id) return `/counterparties/${id}`;
  const screens: Record<string, string> = { dashboard: "/overview", forecast: "/forecast", sources: "/sources", calendar: "/calendar", invoices: "/documents" };
  return screens[ref.screen] ?? "/notifications";
}
export function NotificationBell() {
  const { companyId } = useCompany();
  const resource = useApiResource<Schemas["AlertPage"]>(companyId ? `/v1/companies/${companyId}/alerts?limit=1` : null);
  if (!companyId) return null;
  return <Link href="/notifications" aria-label={resource.data ? `Уведомления: ${resource.data.unread_count} непрочитанных` : "Уведомления"} className="relative rounded-md p-2 text-[color:var(--text-secondary)]"><Bell size={18} />{resource.data && resource.data.unread_count > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-[color:var(--accent)] px-1 text-[10px] text-white">{resource.data.unread_count > 99 ? "99+" : resource.data.unread_count}</span>}{resource.error && <span className="absolute right-0 top-0" title="Не удалось обновить уведомления">!</span>}</Link>;
}
export function NotificationsScreen() {
  const { companyId } = useCompany();
  const [severity, setSeverity] = useState(""); const [kind, setKind] = useState(""); const [unread, setUnread] = useState("");
  const [cursor, setCursor] = useState(""); const [previous, setPrevious] = useState<string[]>([]);
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const base = `/v1/companies/${companyId}`;
  const resource = useApiResource<Schemas["AlertPage"]>(companyId ? `${base}/alerts?${new URLSearchParams({ severity, kind, unread, cursor, limit: "30" })}` : null);
  const reset = () => { setCursor(""); setPrevious([]); };
  async function read(id?: string, value = true) {
    setBusy(true); setError(null);
    try { await api.request(id ? `/v1/alerts/${id}` : `${base}/alerts/read-all`, { method: id ? "PATCH" : "POST", ...(id ? { json: { read: value } } : {}) }); }
    catch (cause) { setError(message(cause)); } finally { setBusy(false); }
  }
  return <section className="space-y-4"><div className="flex flex-wrap justify-between gap-3"><h1 className="text-lg font-semibold">Уведомления</h1><Button disabled={busy || !resource.data?.unread_count} onClick={() => void read()}>Прочитать все</Button></div><div className="grid gap-3 sm:grid-cols-3"><Select label="Важность" value={severity} options={[{ value: "", label: "Все" }, { value: "info", label: "Информация" }, { value: "warning", label: "Внимание" }, { value: "danger", label: "Опасно" }]} onChange={e => { setSeverity(e.target.value); reset(); }} /><Select label="Прочтение" value={unread} options={[{ value: "", label: "Все" }, { value: "true", label: "Непрочитанные" }]} onChange={e => { setUnread(e.target.value); reset(); }} /><Select label="Тип уведомления" value={kind} options={[{ value: "", label: "Все" }, { value: "gap_risk", label: "Риск нехватки денег" }]} onChange={e => { setKind(e.target.value); reset(); }} /></div>
    {resource.loading && <p role="status">Загружаем уведомления…</p>}{(resource.error || error) && <ErrorState description={resource.error || error || ""} action={<Button onClick={resource.refresh}>Обновить</Button>} />}{resource.data?.items.length === 0 && <EmptyState title="Уведомлений нет" />}{resource.data?.items.map(item => <article key={item.id} className="space-y-2 rounded-md border border-[color:var(--border)] p-4"><h2 className="flex items-center gap-2 font-semibold">{item.severity === "danger" || item.severity === "warning" ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}{item.title}{!item.read && <span className="text-xs text-[color:var(--accent)]">Новое</span>}</h2><p className="text-sm">{item.body}</p><p className="text-xs text-[color:var(--text-secondary)]">{new Date(item.created_at).toLocaleString("ru-RU")}</p><div className="flex items-center gap-4"><Link href={alertLink(item.ref)} className="text-sm text-[color:var(--accent)] underline">Открыть</Link><Button size="sm" variant="ghost" disabled={busy} onClick={() => void read(item.id, !item.read)}>{item.read ? "Отметить непрочитанным" : "Прочитано"}</Button></div></article>)}<div className="flex gap-2"><Button variant="outline" disabled={!previous.length || resource.loading} onClick={() => { setCursor(previous.at(-1) ?? ""); setPrevious(previous.slice(0, -1)); }}>Назад</Button><Button variant="outline" disabled={!resource.data?.next_cursor || resource.loading} onClick={() => { setPrevious([...previous, cursor]); setCursor(resource.data!.next_cursor!); }}>Далее</Button></div></section>;
}
