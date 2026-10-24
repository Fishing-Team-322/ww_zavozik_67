"use client";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { CloudUpload, RefreshCw, Plus, CheckCircle2, AlertCircle } from "lucide-react";
import { sourceApi, type CreateSourceInput, type DataSource, type ImportReport, type Job, type SourceKind, type UploadNeedsMapping, type UploadPreview } from "@/src/entities/source";
import { useCompany } from "@/src/features/company-context/CompanyProvider";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";

const sourceNames: Record<SourceKind, string> = {
  upload: "Загрузка файла", onec_bank_file: "Выписка 1С", excel: "Excel", gsheets: "Google Sheets", onec_odata: "1С OData", fns: "ФНС / DaData", manual: "Ручной ввод",
};
const mappingFields = [
  { key: "date", label: "Дата", required: true },
  { key: "amount", label: "Сумма", required: true },
  { key: "direction", label: "Направление", required: false },
  { key: "sign", label: "Знаковая сумма", required: false },
  { key: "counterparty", label: "Контрагент", required: false },
  { key: "inn", label: "ИНН контрагента", required: false },
  { key: "purpose", label: "Назначение", required: false },
  { key: "balance", label: "Остаток на конец дня", required: false },
  { key: "id", label: "ID операции", required: false },
] as const;
const formatDate = (value: string | null | undefined) => value ? new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—";
const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : "Не удалось выполнить операцию";

export function SourcesWorkspace() {
  const { companyId, selectedCompany, status: companyStatus, error: companyError, reloadCompanies } = useCompany();
  const fileRef = useRef<HTMLInputElement>(null);
  const activeCompanyId = useRef(companyId);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [imports, setImports] = useState<ImportReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<{ uploadId: string; data: UploadPreview } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [kind, setKind] = useState<"fns" | "gsheets" | "onec_odata">("gsheets");
  const [title, setTitle] = useState("");
  const [sheetId, setSheetId] = useState("");
  const [sheetRange, setSheetRange] = useState("");
  const [sheetCredential, setSheetCredential] = useState("");
  const [sheetCredentialType, setSheetCredentialType] = useState<"api_key" | "access_token">("api_key");
  const [onecConfig, setOnecConfig] = useState("{}");
  const [onecUsername, setOnecUsername] = useState("");
  const [onecPassword, setOnecPassword] = useState("");
  const processing = job?.status === "queued" || job?.status === "running";

  useEffect(() => { activeCompanyId.current = companyId; }, [companyId]);

  const reload = useCallback(async (id: string) => {
    const [nextSources, nextImports] = await Promise.all([sourceApi.list(id), sourceApi.imports(id)]);
    if (activeCompanyId.current === id) { setSources(nextSources); setImports(nextImports); }
  }, []);

  useEffect(() => {
    setSources([]); setImports([]); setPreview(null); setReport(null); setJob(null); setError(""); setNotice("");
    if (!companyId) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([sourceApi.list(companyId), sourceApi.imports(companyId)])
      .then(([nextSources, nextImports]) => { if (!cancelled) { setSources(nextSources); setImports(nextImports); } })
      .catch(cause => { if (!cancelled) setError(errorMessage(cause)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [companyId]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await sourceApi.job(job.id);
        if (cancelled) return;
        setJob(next);
        if (next.status === "done" && companyId) {
          await reload(companyId);
          if (cancelled) return;
          await reloadCompanies(companyId);
          if (cancelled) return;
          const importId = next.result_ref?.match(/^\/v1\/imports\/([0-9a-f-]+)$/i)?.[1];
          if (importId) {
            const nextReport = await sourceApi.import(importId);
            if (cancelled) return;
            setReport(nextReport);
          }
          setNotice(next.kind === "import" ? "Импорт завершён." : "Синхронизация завершена.");
        }
        if (next.status === "failed") setError(next.error ?? "Задание завершилось с ошибкой");
      } catch (cause) { if (!cancelled) setError(errorMessage(cause)); }
    }, 1500);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [job, companyId, reload, reloadCompanies]);

  async function upload(file: File) {
    if (!companyId) return;
    const requestedCompanyId = companyId;
    if (processing || busy) { setError("Дождитесь завершения текущего задания."); return; }
    setError(""); setNotice(""); setReport(null); setPreview(null);
    if (file.size > 4 * 1024 * 1024) { setError("Максимальный размер файла — 4 МиБ."); return; }
    setBusy(true);
    try {
      const result = await sourceApi.upload(requestedCompanyId, file);
      if (activeCompanyId.current !== requestedCompanyId) return;
      if ((result as UploadNeedsMapping).needs_mapping) {
        const uploadId = (result as UploadNeedsMapping).upload_id;
        const data = await sourceApi.preview(uploadId);
        if (activeCompanyId.current !== requestedCompanyId) return;
        setPreview({ uploadId, data });
        setMapping(data.proposed_mapping ?? {});
        setNotice("Проверьте сопоставление столбцов перед импортом.");
      } else { setJob(result as Job); setNotice("Файл принят. Ожидаем обработки."); }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function saveMapping() {
    if (!preview) return;
    if (!mapping.date || !mapping.amount || !(mapping.direction || mapping.sign)) { setError("Сопоставьте дату, сумму и направление либо знаковую сумму."); return; }
    const requestedCompanyId = companyId;
    setBusy(true); setError("");
    try {
      const valid = Object.fromEntries(Object.entries(mapping).filter(([, value]) => value));
      const nextJob = await sourceApi.map(preview.uploadId, valid);
      if (activeCompanyId.current !== requestedCompanyId) return;
      setJob(nextJob);
      setPreview(null);
      setNotice("Сопоставление сохранено. Ожидаем обработки.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function connect() {
    if (!companyId) return;
    const requestedCompanyId = companyId;
    setError(""); setBusy(true);
    try {
      let config: Record<string, unknown> = {};
      if (kind === "gsheets") {
        config = { spreadsheet_id: sheetId.trim() };
        if (sheetRange.trim()) config.range = sheetRange.trim();
        if (sheetCredential.trim()) config[sheetCredentialType] = sheetCredential.trim();
      }
      if (kind === "onec_odata") {
        const parsed: unknown = JSON.parse(onecConfig);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Конфигурация 1С должна быть JSON-объектом.");
        config = { ...(parsed as Record<string, unknown>), username: onecUsername, password: onecPassword };
      }
      const input: CreateSourceInput = { kind, title: title.trim() || sourceNames[kind], config };
      await sourceApi.create(requestedCompanyId, input);
      await reload(requestedCompanyId);
      if (activeCompanyId.current !== requestedCompanyId) return;
      setConnectOpen(false);
      setNotice("Источник подключён. Проверьте соединение и запустите синхронизацию.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function sourceAction(source: DataSource, action: "test" | "sync") {
    if (action === "sync" && processing) { setError("Дождитесь завершения текущего задания."); return; }
    const requestedCompanyId = companyId;
    setError(""); setNotice(""); setBusy(true);
    try {
      if (action === "test") {
        const result = await sourceApi.test(source.id);
        if (activeCompanyId.current === requestedCompanyId) setNotice(result.message);
      } else {
        const nextJob = await sourceApi.sync(source.id);
        if (activeCompanyId.current !== requestedCompanyId) return;
        setJob(nextJob);
        setNotice(`Синхронизация «${source.title}» поставлена в очередь.`);
      }
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void upload(file);
  }

  if (companyStatus === "unauthorized") return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">Чтобы подключить источники, <Link href="/login" className="font-medium text-[color:var(--accent)] underline">войдите в аккаунт</Link>.</div>;
  if (companyStatus === "loading" && !companyId) return <p className="text-[13px] text-[color:var(--text-secondary)]">Загружаем компании…</p>;
  if (companyStatus === "error") return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">{companyError ?? "Не удалось загрузить компании"}</div>;
  if (companyStatus === "ready" && !companyId) return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">У вас пока нет компании. <Link href="/companies/new" className="font-medium text-[color:var(--accent)] underline">Создать первую компанию</Link></div>;

  return <div className="min-w-0 space-y-6 text-[color:var(--text-primary)]">
    <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--border)] pb-4"><div><h1 className="text-[20px] font-semibold tracking-tight">Источники данных</h1><p className="mt-1 text-[13px] text-[color:var(--text-secondary)]">{selectedCompany?.name ?? "Компания"} · подключение выписок и синхронизаций</p></div><Button type="button" variant="outline" size="lg" onClick={() => setConnectOpen(value => !value)}><Plus aria-hidden="true"/> Подключить источник</Button></header>
    {error && <div role="alert" className="flex items-start gap-2 border-l-2 border-[color:var(--danger)] bg-[color:var(--surface-subtle)] px-3 py-2 text-[13px]"><AlertCircle size={16} className="mt-0.5 shrink-0"/>{error}</div>}
    {notice && <p role="status" className="flex items-center gap-2 text-[12px] text-[color:var(--text-secondary)]"><CheckCircle2 size={15} className="text-[color:var(--accent)]"/>{notice}</p>}
    {connectOpen && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4 sm:p-5"><h2 className="mb-4 text-[16px] font-semibold">Новое подключение</h2><div className="grid gap-4 sm:grid-cols-2"><Select label="Тип источника" size="lg" value={kind} options={[{ value: "gsheets", label: "Google Sheets" }, { value: "onec_odata", label: "1С OData" }, { value: "fns", label: "ФНС / DaData" }]} onChange={event => setKind(event.target.value as typeof kind)}/><Input label="Название подключения" value={title} onChange={event => setTitle(event.target.value)} placeholder={sourceNames[kind]} className="h-8"/></div>
      {kind === "gsheets" && <div className="mt-4 grid gap-4 sm:grid-cols-2"><Input label="Spreadsheet ID" required value={sheetId} onChange={event => setSheetId(event.target.value)} className="h-8"/><Input label="Диапазон (необязательно)" value={sheetRange} onChange={event => setSheetRange(event.target.value)} placeholder="A1:Z10001" className="h-8"/><Select label="Способ доступа" size="lg" value={sheetCredentialType} options={[{ value: "api_key", label: "API key" }, { value: "access_token", label: "Access token" }]} onChange={event => setSheetCredentialType(event.target.value as typeof sheetCredentialType)}/><Input label="Ключ или токен" type="password" value={sheetCredential} onChange={event => setSheetCredential(event.target.value)} className="h-8" helperText="Не возвращается в ответах API."/></div>}
      {kind === "onec_odata" && <div className="mt-4 space-y-3"><p className="text-[12px] text-[color:var(--text-secondary)]">Укажите base_url, company_account, account_map и collections по конфигурации вашей 1С. Адрес должен быть разрешён оператором сервиса.</p><label className="block text-[12px] font-medium">Конфигурация JSON<textarea className="mt-1 min-h-28 w-full rounded-[5px] border border-[color:var(--border)] bg-[color:var(--surface)] p-2 font-mono text-[12px] outline-none focus:border-[color:var(--accent)]" value={onecConfig} onChange={event => setOnecConfig(event.target.value)} /></label><div className="grid gap-4 sm:grid-cols-2"><Input label="Пользователь 1С" value={onecUsername} onChange={event => setOnecUsername(event.target.value)} className="h-8"/><Input label="Пароль 1С" type="password" value={onecPassword} onChange={event => setOnecPassword(event.target.value)} className="h-8"/></div></div>}
      {kind === "fns" && <p className="mt-3 text-[12px] text-[color:var(--text-secondary)]">{selectedCompany?.inn ? "Ключ DaData настраивает оператор сервиса." : "У выбранной компании нет ИНН. Для проверки ФНС добавьте ИНН в реквизитах компании."}</p>}
      <div className="mt-4 flex gap-2"><Button type="button" size="lg" disabled={busy || kind === "gsheets" && (!sheetId.trim() || !sheetCredential.trim()) || kind === "fns" && !selectedCompany?.inn} onClick={() => void connect()}>{busy ? "Подключаем…" : "Подключить"}</Button><Button type="button" size="lg" variant="ghost" onClick={() => setConnectOpen(false)}>Отмена</Button></div>
    </section>}
    <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-[16px] font-semibold">Подключённые источники</h2><span className="text-[12px] text-[color:var(--text-secondary)]">{sources.length}</span></div>{loading ? <p className="text-[13px] text-[color:var(--text-secondary)]">Загружаем источники…</p> : sources.length ? <div className="grid gap-3 lg:grid-cols-2">{sources.map(source => <article key={source.id} className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 className="truncate text-[13px] font-semibold">{source.title}</h3><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">{sourceNames[source.kind] ?? source.kind}</p></div><span className="rounded-[4px] bg-[color:var(--surface-subtle)] px-2 py-0.5 text-[11px] text-[color:var(--text-secondary)]">{source.enabled ? source.status : "Отключён"}</span></div><div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-[color:var(--border)] pt-3 text-[12px] text-[color:var(--text-secondary)]"><span>Операций: <b className="font-medium tabular-nums text-[color:var(--text-primary)]">{source.records}</b></span><span>Последняя синхронизация: {formatDate(source.last_synced_at)}</span></div>{source.error && <p className="mt-2 text-[12px] text-[color:var(--danger)]">{source.error}</p>}{source.enabled && ["gsheets", "onec_odata", "fns"].includes(source.kind) && <div className="mt-3 flex gap-2"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void sourceAction(source, "test")}>Проверить</Button><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void sourceAction(source, "sync")}><RefreshCw aria-hidden="true"/>Синхронизировать</Button></div>}</article>)}</div> : <p className="border-y border-[color:var(--border)] py-4 text-[13px] text-[color:var(--text-secondary)]">Источников пока нет. Загрузите выписку или добавьте подключение.</p>}</section>
    <section className="space-y-3"><div><h2 className="text-[16px] font-semibold">Загрузка выписки</h2><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">CSV, XLSX или 1CClientBankExchange · до 4 МиБ</p></div><input ref={fileRef} type="file" accept=".csv,.xlsx,.txt,.1c" className="sr-only" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }}/><div role="button" tabIndex={0} onClick={() => fileRef.current?.click()} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileRef.current?.click(); } }} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={`flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-[6px] border border-dashed px-4 py-4 text-center transition-colors focus-visible:outline-2 focus-visible:outline-[color:var(--accent)] ${dragging ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)]" : "border-[color:var(--border)] bg-[color:var(--surface-subtle)] hover:border-[color:var(--accent)]"}`}><CloudUpload size={23} className="text-[color:var(--text-secondary)]" aria-hidden="true"/><p className="mt-2 text-[13px] font-medium">{busy ? "Обрабатываем запрос…" : "Перетащите файл сюда или нажмите для выбора"}</p><p className="mt-1 text-[11px] text-[color:var(--text-secondary)]">Загрузка файла запускает импорт только после проверки колонок, если она потребуется.</p></div></section>
    {preview && <section className="min-w-0 rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><h2 className="text-[16px] font-semibold">Сопоставление колонок</h2><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">Проверьте предложенные поля. Для знаковой суммы укажите тот же столбец в «Сумма» и «Знаковая сумма».</p><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{mappingFields.map(field => <Select key={field.key} label={`${field.label}${field.required ? " *" : ""}`} size="lg" value={mapping[field.key] ?? ""} options={[{ value: "", label: "Не сопоставлено" }, ...preview.data.columns.map(column => ({ value: column, label: column }))]} onChange={event => setMapping(current => ({ ...current, [field.key]: event.target.value }))}/>)}</div><div className="mt-4 max-w-full overflow-x-auto border border-[color:var(--border)]"><table className="min-w-full text-left text-[12px]"><thead className="bg-[color:var(--surface-subtle)]"><tr>{preview.data.columns.map((column, index) => <th key={`${column}-${index}`} className="whitespace-nowrap border-r border-[color:var(--border)] px-2 py-1.5 font-medium">{column}</th>)}</tr></thead><tbody>{preview.data.rows.slice(0, 5).map((row, index) => <tr key={index} className="border-t border-[color:var(--border)]">{row.map((cell, cellIndex) => <td key={cellIndex} className="max-w-48 truncate border-r border-[color:var(--border)] px-2 py-1.5" title={cell}>{cell}</td>)}</tr>)}</tbody></table></div><div className="mt-4 flex gap-2"><Button type="button" size="lg" disabled={busy} onClick={() => void saveMapping()}>Запустить импорт</Button><Button type="button" variant="ghost" size="lg" onClick={() => setPreview(null)}>Отмена</Button></div></section>}
    {job && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><div className="flex justify-between gap-3 text-[13px]"><h2 className="font-semibold">{job.kind === "import" ? "Импорт выписки" : "Синхронизация"}</h2><span className="text-[color:var(--text-secondary)]">{job.status === "queued" ? "В очереди" : job.status === "running" ? "Обработка" : job.status === "done" ? "Готово" : "Ошибка"}</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[color:var(--surface-subtle)]"><div className="h-full bg-[color:var(--accent)] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, job.progress * 100))}%` }}/></div><p className="mt-1 text-[11px] tabular-nums text-[color:var(--text-secondary)]">{Math.round(job.progress * 100)}% · статус задания из API</p>{job.error && <p className="mt-2 text-[12px] text-[color:var(--danger)]">{job.error}</p>}</section>}
    {report && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><h2 className="text-[16px] font-semibold">Результат импорта</h2><div className="mt-3 flex flex-wrap gap-5 text-[13px]"><span>Добавлено: <b className="tabular-nums">{report.added}</b></span><span>Дубли: <b className="tabular-nums">{report.duplicates}</b></span><span>Ошибки: <b className="tabular-nums">{report.errors.length}</b></span></div>{report.errors.length > 0 && <ul className="mt-3 space-y-1 border-t border-[color:var(--border)] pt-3 text-[12px] text-[color:var(--text-secondary)]">{report.errors.slice(0, 10).map((issue, index) => <li key={index}>Строка {issue.row ?? "—"}: {issue.message ?? issue.code ?? "Ошибка обработки"}</li>)}</ul>}</section>}
    <section className="min-w-0"><h2 className="mb-3 text-[16px] font-semibold">История импортов</h2><div className="max-w-full overflow-x-auto border-y border-[color:var(--border)]"><table className="w-full min-w-[620px] text-left text-[12px]"><thead><tr className="text-[color:var(--text-secondary)]"><th className="px-2 py-2 font-medium">Дата</th><th className="px-2 py-2 font-medium">Источник</th><th className="px-2 py-2 text-right font-medium">Добавлено</th><th className="px-2 py-2 text-right font-medium">Дубли</th><th className="px-2 py-2 text-right font-medium">Ошибки</th></tr></thead><tbody>{imports.length ? imports.map(item => <tr key={item.id} className="border-t border-[color:var(--border)] hover:bg-[color:var(--surface-subtle)]"><td className="px-2 py-2">{formatDate(item.started_at)}</td><td className="px-2 py-2">{item.source?.kind ? sourceNames[item.source.kind as SourceKind] ?? item.source.kind : item.source_id}</td><td className="px-2 py-2 text-right tabular-nums">{item.added}</td><td className="px-2 py-2 text-right tabular-nums">{item.duplicates}</td><td className="px-2 py-2 text-right tabular-nums">{item.errors?.length ?? 0}</td></tr>) : <tr><td colSpan={5} className="px-2 py-4 text-[color:var(--text-secondary)]">Импортов пока нет.</td></tr>}</tbody></table></div></section>
    {imports.length > 0 && <div className="max-w-sm"><Select label="Посмотреть подробности прошлого импорта" size="lg" value={report?.id ?? ""} options={[{ value: "", label: "Выберите импорт" }, ...imports.map(item => ({ value: item.id, label: `${formatDate(item.started_at)} · ${item.added} добавлено` }))]} onChange={async event => { if (!event.target.value) { setReport(null); return; } try { setReport(await sourceApi.import(event.target.value)); } catch (cause) { setError(errorMessage(cause)); } }}/></div>}
  </div>;
}
