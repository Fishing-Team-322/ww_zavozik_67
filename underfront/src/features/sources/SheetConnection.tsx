"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { useRef, useState } from "react";
import { api, message, type Job, type Source } from "@/src/shared/api";
import { Button, Input, Select, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
type Preview = { source_id: string; columns: string[]; rows: string[][]; proposed_mapping: Record<string, string>; data_mode?: string };
const fields = [{ key: "date", label: "Дата" }, { key: "amount", label: "Сумма" }, { key: "direction", label: "Направление" }, { key: "counterparty", label: "Контрагент" }, { key: "balance", label: "Остаток на конец дня" }, { key: "purpose", label: "Назначение" }, { key: "inn", label: "ИНН" }, { key: "id", label: "ID операции" }];
export function SheetConnection({ companyId, onChanged }: { companyId: string; onChanged: () => void }) {
  const [id, setId] = useState(""); const [range, setRange] = useState(""); const [credential, setCredential] = useState(""); const [access, setAccess] = useState("api_key");
  const [preview, setPreview] = useState<Preview | null>(null); const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState(""); const [sourceId, setSourceId] = useState("");
  const submitLock = useRef(false);
  async function inspect(event: React.FormEvent) {
    event.preventDefault();
    if (submitLock.current) return;
    submitLock.current = true;
    setBusy(true); setError(""); setNotice("");
    setPreview(null); setMapping({}); setSourceId("");
    try {
      const source = await api.request<Source>(`/v1/companies/${companyId}/sources`, { method: "POST", json: { kind: "gsheets", title: "Google Sheets · банковские операции", config: { spreadsheet_id: id.trim(), ...(range.trim() ? { range: range.trim() } : {}), [access]: credential } } });
      setSourceId(source.id); setCredential(""); onChanged();
      const data = await api.request<Preview>(`/v1/sources/${source.id}/sheet-preview`, { method: "POST" });
      setPreview(data); setMapping(data.proposed_mapping);
    } catch (cause) { setError(message(cause)); } finally { submitLock.current = false; setBusy(false); }
  }
  async function confirm() {
    if (!preview || submitLock.current) return;
    submitLock.current = true;
    setBusy(true); setError("");
    try {
      const job = await api.request<Job>(`/v1/sources/${preview.source_id}/sheet-mapping`, { method: "POST", json: { mapping } });
      const done = await api.waitForJob(job); setNotice(`Импорт таблицы завершён. Новых операций: ${done.result?.added ?? 0}, повторов: ${done.result?.duplicates ?? 0}.`); setPreview(null); onChanged();
    } catch (cause) { setError(message(cause)); } finally { submitLock.current = false; setBusy(false); }
  }
  async function retryPreview() {
    if (!sourceId || submitLock.current) return;
    submitLock.current = true;
    setBusy(true);
    try {
      const data = await api.request<Preview>(`/v1/sources/${sourceId}/sheet-preview`, { method: "POST" });
      setPreview(data); setMapping(data.proposed_mapping); setError("");
    } catch (cause) { setError(message(cause)); }
    finally { submitLock.current = false; setBusy(false); }
  }
  return <section id="sheet-connection" className="min-w-0 space-y-3 rounded-md border border-[color:var(--border)] p-5"><ContentHeading level={2} >Google Sheets · предпросмотр и импорт</ContentHeading><ContentText variant="description" tone="muted" >Укажите ID документа из URL и диапазон листа, например Лист1!A1:Z1000. API key читает только доступную ему таблицу; для закрытой таблицы нужен access token с правом чтения. ПУЛЬС не выдаёт эти права автоматически. После отзыва доступа синхронизация остановится с ошибкой.</ContentText>
    <form onSubmit={inspect} className="grid gap-3 sm:grid-cols-2"><Input label="ID таблицы Google Sheets" required value={id} onChange={event => setId(event.target.value)} /><Input label="Лист и диапазон Google Sheets" value={range} onChange={event => setRange(event.target.value)} /><Select density="form" label="Доступ к Google Sheets" value={access} onChange={event => setAccess(event.target.value)} options={[{ value: "api_key", label: "API key · доступная таблица" }, { value: "access_token", label: "Access token · право чтения" }]} /><Input label="Ключ доступа Google Sheets" type="password" required value={credential} autoComplete="off" onChange={event => setCredential(event.target.value)} /><Button disabled={busy}>Сохранить доступ и показать столбцы</Button></form>
    {busy && <p role="status">Обрабатываем таблицу…</p>}{error && <p role="alert">{error}</p>}{sourceId && !preview && error && <Button variant="outline" disabled={busy} onClick={() => void retryPreview()}>Повторить предпросмотр</Button>}{notice && <p role="status">{notice}</p>}
    {preview && <div className="space-y-3"><ContentHeading level={3} >Столбцы Google Sheets · проверьте сопоставление</ContentHeading>{preview.data_mode === "mock" && <p>ДЕМОНСТРАЦИЯ / MOCK · синтетическая таблица</p>}<div className="grid gap-3 sm:grid-cols-2">{fields.map(field => <Select density="form" key={field.key} label={`Sheets: ${field.label}`} value={mapping[field.key] || ""} onChange={event => setMapping({ ...mapping, [field.key]: event.target.value })} options={[{ value: "", label: "Не указан" }, ...preview.columns.map(column => ({ value: column, label: column }))]} />)}</div><div className="max-w-full overflow-auto"><Table ><TableHeader><TableRow>{preview.columns.map(column => <TableHead key={column} >{column}</TableHead>)}</TableRow></TableHeader><TableBody>{preview.rows.map((row, i) => <TableRow key={i}>{row.map((cell, j) => <TableCell key={j} >{cell}</TableCell>)}</TableRow>)}</TableBody></Table></div><ContentText variant="meta" >Таблица должна содержать фактические банковские операции. Плановые счета загружайте в раздел документов; незаданный остаток останется неизвестным.</ContentText><Button disabled={busy} onClick={() => void confirm()}>Подтвердить столбцы и импортировать таблицу</Button></div>}
  </section>;
}
