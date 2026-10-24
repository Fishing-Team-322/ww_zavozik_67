"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { OneCConnection } from "./OneCConnection";
import { RegistryDocuments } from "./RegistryDocuments";
import { MarketplaceConnections } from "./MarketplaceConnections";
import { FNSOpenData } from "./FNSOpenData";
import { SourceCredentials } from "./SourceCredentials";
import { SheetConnection } from "./SheetConnection";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { api } from "@/src/shared/api";
import { Dialog, ConfirmDialog, Checkbox, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import type { Schemas } from "@/src/shared/api";
import { rubles } from "@/src/entities/forecast";
import { CloudUpload, RefreshCw, CheckCircle2, AlertCircle, Landmark, Database, FileSpreadsheet, Store, FileCheck2, ShieldCheck, X } from "lucide-react";
import { sourceApi, type CreateSourceInput, type DataSource, type ImportReport, type Job, type SourceKind, type UploadNeedsMapping, type UploadPreview } from "@/src/entities/source";
import { useCompany } from "@/src/features/company-context/CompanyProvider";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";

const sourceNames: Record<SourceKind, string> = {
  upload: "Загрузка файла", onec_bank_file: "Выписка 1С", excel: "Excel", gsheets: "Google Sheets", onec_odata: "1С OData", fns: "DaData · сведения об организации", wb: "Wildberries · финансовый отчёт", ozon: "Ozon · финансовый отчёт", manual: "Ручной ввод",
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
const paymentStatus = (status: string) => ({ expected: "Ожидает оплаты", paid: "Оплачен", partially_paid: "Частично оплачен", partial: "Частично оплачен", cancelled: "Отменён", undated: "Без срока", needs_reconciliation: "Требует сверки" })[status] ?? status;
const errorMessage = (cause: unknown) => cause instanceof Error ? cause.message : "Не удалось выполнить операцию";
const sourceStatusNames: Record<string, string> = { ok: "Подключён", error: "Ошибка подключения", pending: "Ожидает проверки", syncing: "Синхронизируется", mapping_required: "Нужно сопоставить столбцы" };
const importStatusNames: Record<string, string> = { done: "Завершён", failed: "Ошибка", error: "Ошибка", queued: "В очереди", running: "Обрабатывается" };
const syncableKinds: SourceKind[] = ["gsheets", "onec_odata", "fns", "wb", "ozon"];

export function SourcesWorkspace() {
  const { companyId } = useCompany();
  return <CompanySourcesWorkspace key={companyId ?? "no-company"} />;
}

function CompanySourcesWorkspace() {
  const { companyId, selectedCompany, status: companyStatus, error: companyError, reloadCompanies } = useCompany();
  const plans = useApiResource<Schemas["PlannedEvent"][]>(companyId ? `/v1/companies/${companyId}/events` : null);
  const oneCPlans = plans.data?.filter(event => event.source === "onec_odata") ?? [];
  const fileRef = useRef<HTMLInputElement>(null);
  const activeCompanyId = useRef(companyId);
  const reloadRevision = useRef(0);
  const reportRequest = useRef<AbortController | null>(null);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [imports, setImports] = useState<ImportReport[]>([]);
  const [loading, setLoading] = useState(!!companyId);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<{ uploadId: string; data: UploadPreview } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [activeWizard, setActiveWizard] = useState<"bank" | "onec" | "sheets" | "marketplaces" | "fns" | null>(null);
  const [fnsSection, setFnsSection] = useState<"registry" | "snapshot" | "company">("registry");
  const capabilities = useApiResource<{ sandbox: boolean; dadata_configured: boolean; fns_snapshot_configured: boolean }>(companyId ? `/v1/companies/${companyId}/integration-capabilities` : null);
  const kind = "fns" as const;
  const [title, setTitle] = useState("");
  const [editingSource, setEditingSource] = useState<DataSource | null>(null);
  const [sourceTitle, setSourceTitle] = useState("");
  const [deletingSource, setDeletingSource] = useState<DataSource | null>(null);
  const [keepData, setKeepData] = useState(true);
  const [pollError, setPollError] = useState("");
  const refreshPlans = plans.refresh;
  const processing = job?.status === "queued" || job?.status === "running";

  useEffect(() => {
    activeCompanyId.current = companyId;
    return () => {
      activeCompanyId.current = null;
      reportRequest.current?.abort();
    };
  }, [companyId]);

  const reload = useCallback(async (id: string) => {
    if (activeCompanyId.current !== id) return;
    const revision = ++reloadRevision.current;
    try {
      const [nextSources, nextImports] = await Promise.all([sourceApi.list(id), sourceApi.imports(id)]);
      if (activeCompanyId.current === id && revision === reloadRevision.current) { setSources(nextSources); setImports(nextImports); }
    } catch (cause) {
      if (activeCompanyId.current === id && revision === reloadRevision.current) throw cause;
    }
  }, []);

  useEffect(() => {
    if (!companyId) return;
    let cancelled = false;
    // Cleanup can cancel the initial load before Strict Mode replays the effect.
    const timer = window.setTimeout(() => {
      void reload(companyId)
        .catch(cause => { if (!cancelled) setError(errorMessage(cause)); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [companyId, reload]);

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed" || pollError) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const next = await sourceApi.job(job.id);
        if (cancelled) return;
        if (next.status === "done" && companyId) {
          await reload(companyId);
          if (cancelled) return;
          await reloadCompanies();
          if (cancelled) return;
          const importId = next.result_ref?.match(/^\/v1\/imports\/([0-9a-f-]+)$/i)?.[1];
          if (importId) {
            const nextReport = await sourceApi.import(importId);
            if (cancelled) return;
            setReport(nextReport);
          }
          setNotice(next.kind === "import" ? "Импорт завершён." : "Синхронизация завершена.");
          refreshPlans();
          api.invalidate();
        }
        if (next.status === "failed") setError(next.error ?? "Задание завершилось с ошибкой");
        if (!cancelled) setJob(next);
      } catch (cause) { if (!cancelled) setPollError(errorMessage(cause)); }
    }, 1500);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [job, pollError, companyId, reload, reloadCompanies, refreshPlans]);

  async function updateSource(source: DataSource, input: { title?: string; enabled?: boolean }) {
    if (busyRef.current || !companyId) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try { await sourceApi.update(source.id, input); await reload(companyId); setEditingSource(null); setNotice("Источник обновлён."); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function deleteSource() {
    if (busyRef.current || !deletingSource || !companyId) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try {
      await sourceApi.remove(deletingSource.id, keepData);
      await reload(companyId);
      if (activeCompanyId.current !== companyId) return;
      await reloadCompanies();
      setDeletingSource(null); setNotice("Источник удалён.");
    }
    catch (cause) { setError(errorMessage(cause)); }
    finally { busyRef.current = false; setBusy(false); }
  }

  async function upload(file: File) {
    if (/\.pdf$/i.test(file.name)) { setError("PDF ЕГРЮЛ/ЕГРИП загрузите в разделе «Документы ФНС». Для банковских операций нужны CSV, XLSX или файл 1С. Поддержка произвольных банковских PDF отсутствует."); setFnsSection("registry"); setActiveWizard("fns"); return; }
    if (!companyId) return;
    const requestedCompanyId = companyId;
    if (processing || busyRef.current) { setError("Дождитесь завершения текущего задания."); return; }
    reportRequest.current?.abort();
    setError(""); setNotice(""); setReport(null); setPreview(null);
    if (file.size > 4 * 1024 * 1024) { setError("Максимальный размер файла — 4 МиБ."); return; }
    busyRef.current = true;
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
    finally { busyRef.current = false; setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function saveMapping() {
    if (!preview || busyRef.current) return;
    if (!mapping.date || !mapping.amount || !(mapping.direction || mapping.sign)) { setError("Сопоставьте дату, сумму и направление либо знаковую сумму."); return; }
    const requestedCompanyId = companyId;
    busyRef.current = true;
    setBusy(true); setError("");
    try {
      const valid = Object.fromEntries(Object.entries(mapping).filter(([, value]) => value));
      const nextJob = await sourceApi.map(preview.uploadId, valid);
      if (activeCompanyId.current !== requestedCompanyId) return;
      setJob(nextJob);
      setPreview(null);
      setNotice("Сопоставление сохранено. Ожидаем обработки.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { busyRef.current = false; setBusy(false); }
  }

  async function connect() {
    if (!companyId || busyRef.current) return;
    busyRef.current = true;
    const requestedCompanyId = companyId;
    setError(""); setBusy(true);
    try {
      const config: Record<string, unknown> = {};
      const input: CreateSourceInput = { kind, title: title.trim() || sourceNames[kind], config };
      await sourceApi.create(requestedCompanyId, input);
      await reload(requestedCompanyId);
      if (activeCompanyId.current !== requestedCompanyId) return;
      setFnsSection("registry");
      setNotice("Настройки источника сохранены. Проверьте соединение и запустите синхронизацию.");
    } catch (cause) { setError(errorMessage(cause)); }
    finally { busyRef.current = false; setBusy(false); }
  }

  async function sourceAction(source: DataSource, action: "test" | "sync") {
    if (busyRef.current) return;
    if (action === "sync" && processing) { setError("Дождитесь завершения текущего задания."); return; }
    const requestedCompanyId = companyId;
    busyRef.current = true;
    setError(""); setNotice(""); setBusy(true);
    try {
      if (action === "test") {
        const result = await sourceApi.test(source.id);
        if (requestedCompanyId) await reload(requestedCompanyId);
        if (activeCompanyId.current === requestedCompanyId) setNotice(result.message);
      } else {
        const nextJob = await sourceApi.sync(source.id);
        if (activeCompanyId.current !== requestedCompanyId) return;
        setJob(nextJob);
        setNotice(`Синхронизация «${source.title}» поставлена в очередь.`);
      }
    } catch (cause) { setError(errorMessage(cause)); if (requestedCompanyId) void reload(requestedCompanyId).catch(() => {}); }
    finally { busyRef.current = false; setBusy(false); }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void upload(file);
  }

  async function selectReport(id: string) {
    reportRequest.current?.abort();
    reportRequest.current = null;
    setReport(null);
    if (!id) { setReport(null); return; }
    const controller = new AbortController();
    reportRequest.current = controller;
    try {
      const nextReport = await sourceApi.import(id, controller.signal);
      if (!controller.signal.aborted && activeCompanyId.current === companyId) setReport(nextReport);
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (reportRequest.current === controller) reportRequest.current = null;
    }
  }

  if (companyStatus === "unauthorized") return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">Чтобы подключить источники, <Link href="/login" className="font-medium text-[color:var(--accent)] underline">войдите в аккаунт</Link>.</div>;
  if (companyStatus === "loading" && !companyId) return <ContentText variant="description" tone="muted" >Загружаем компании…</ContentText>;
  if (companyStatus === "error") return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">{companyError ?? "Не удалось загрузить компании"}</div>;
  if (companyStatus === "ready" && !companyId) return <div className="rounded-[6px] border border-[color:var(--border)] p-6 text-[13px]">У вас пока нет компании. <Link href="/companies/new" className="font-medium text-[color:var(--accent)] underline">Создать первую компанию</Link></div>;

  return <div className="min-w-0 space-y-6 text-[color:var(--text-primary)]">
    <header><ContentHeading level={1}>Источники данных</ContentHeading><ContentText variant="description" tone="muted" className="mt-1">Подключайте данные и следите за обновлениями в одном месте.</ContentText></header>
    {error && <div role="alert" className="flex items-start gap-2 border-l-2 border-[color:var(--danger)] bg-[color:var(--surface-subtle)] px-3 py-2 text-[13px]"><AlertCircle size={16} className="mt-0.5 shrink-0"/>{error}<Button variant="outline" size="sm" disabled={busy || !companyId} onClick={async () => { if (!companyId) return; setError(""); try { await reload(companyId); } catch (cause) { setError(errorMessage(cause)); } }}>Обновить список</Button></div>}
    {notice && <ContentText variant="description" tone="muted" role="status" className="flex items-center gap-2"><CheckCircle2 size={15} className="text-[color:var(--accent)]"/>{notice}</ContentText>}
    <section className="space-y-3"><div className="flex items-center justify-between"><ContentHeading level={2}>Подключённые источники</ContentHeading><span className="text-xs text-[color:var(--text-secondary)]">{sources.length}</span></div>
      {loading ? <ContentText variant="description" tone="muted">Загружаем источники…</ContentText> : sources.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{sources.map(source => <article key={source.id} className="min-w-0 rounded-[6px] border border-[color:var(--border)] p-3">
        <div className="flex items-start justify-between gap-2"><div className="min-w-0"><ContentHeading level={3} className="truncate">{source.title}</ContentHeading><ContentText variant="meta" className="mt-0.5">{sourceNames[source.kind] ?? source.kind}{source.data_mode === "mock" ? " · Демо" : ""}</ContentText></div><span className={`shrink-0 text-xs ${source.enabled && source.status === "error" ? "text-[color:var(--danger)]" : source.enabled && source.status === "ok" ? "text-[color:var(--success)]" : "text-[color:var(--text-secondary)]"}`}>{source.enabled ? sourceStatusNames[source.status] ?? source.status : "Отключён"}</span></div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[color:var(--text-secondary)]"><span>{["wb", "ozon"].includes(source.kind) ? "Строк отчёта" : "Операций"}: <b className="font-medium tabular-nums text-[color:var(--text-primary)]">{source.records}</b></span><span>Обновлён: {formatDate(source.last_synced_at)}</span></div>
        {source.error && <ContentText variant="meta" tone="danger" className="mt-2">{source.error}</ContentText>}
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-[color:var(--border)] pt-2">
          {syncableKinds.includes(source.kind) && <Button type="button" variant="outline" size="sm" disabled={busy || processing || !source.enabled} onClick={() => void sourceAction(source, "sync")}><RefreshCw aria-hidden="true"/>Синхронизировать</Button>}
          {["gsheets", "onec_odata", "wb", "ozon"].includes(source.kind) ? <SourceCredentials id={source.id} kind={source.kind} triggerLabel="Настроить" onChanged={() => { if (companyId) void reload(companyId).catch(cause => setError(errorMessage(cause))); }} /> : <Button variant="outline" size="sm" disabled={busy || processing} onClick={() => { setSourceTitle(source.title); setEditingSource(source); }}>Настроить</Button>}
          <Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => void updateSource(source, { enabled: !source.enabled })}>{source.enabled ? "Отключить" : "Включить"}</Button>
        </div>
        <details className="mt-2 text-xs text-[color:var(--text-secondary)]"><summary className="cursor-pointer">Ещё действия</summary><div className="mt-2 flex flex-wrap gap-1.5">{syncableKinds.includes(source.kind) && <Button variant="ghost" size="sm" disabled={busy} onClick={() => void sourceAction(source, "test")}>Проверить</Button>}{["gsheets", "onec_odata", "wb", "ozon"].includes(source.kind) && <Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => { setSourceTitle(source.title); setEditingSource(source); }}>Переименовать</Button>}<Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => { setKeepData(true); setDeletingSource(source); }}>Удалить</Button></div></details>
      </article>)}</div> : <ContentText variant="description" tone="muted" className="border-y border-[color:var(--border)] py-4">Источников пока нет. Начните с банковской выписки.</ContentText>}
    </section>
    <section className="space-y-3"><ContentHeading level={2}>Добавить источник</ContentHeading><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {([{ key: "bank", title: "Банковская выписка", description: "CSV, XLSX или файл 1С", icon: Landmark }, { key: "onec", title: "1С", description: "Подключение по сети или файл", icon: Database }, { key: "sheets", title: "Google Sheets", description: "Операции из таблицы", icon: FileSpreadsheet }, { key: "marketplaces", title: "Маркетплейсы", description: "Wildberries и Ozon", icon: Store }, { key: "fns", title: "ФНС", description: "Документы и проверка реквизитов", icon: FileCheck2 }] as const).map(option => { const Icon = option.icon; return <button type="button" key={option.key} onClick={() => setActiveWizard(option.key)} className={`flex min-h-20 items-center gap-3 rounded-[6px] border p-4 text-left transition-colors hover:border-[color:var(--accent)] hover:bg-[color:var(--surface-subtle)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring-strong)] ${option.key === "bank" ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)]" : "border-[color:var(--border)]"}`}><Icon size={20} className="shrink-0 text-[color:var(--accent)]" aria-hidden="true"/><span className="min-w-0"><span className="block text-sm font-medium">{option.title}</span><span className="block text-xs text-[color:var(--text-secondary)]">{option.description}</span></span></button>; })}
    </div></section>
    <Dialog open={activeWizard !== null} title={activeWizard === "bank" ? "Банковская выписка" : activeWizard === "onec" ? "Подключение 1С" : activeWizard === "sheets" ? "Google Sheets" : activeWizard === "marketplaces" ? "Маркетплейсы" : "Сведения ФНС"} className="max-w-4xl" onClose={() => setActiveWizard(null)} dismissDisabled={busy} headerActions={<Button variant="ghost" size="icon" aria-label="Закрыть" disabled={busy} onClick={() => setActiveWizard(null)}><X aria-hidden="true" /></Button>}>
      {error && <ContentText variant="description" tone="danger" role="alert" className="mb-4">{error}</ContentText>}
      {activeWizard === "bank" && <div className="space-y-5">
        <section id="bank-import" className="space-y-3"><ContentText variant="description" tone="muted">CSV, XLSX или 1CClientBankExchange · до 4 МиБ. Если столбцы не распознаны, вы сможете сопоставить их перед импортом.</ContentText><input ref={fileRef} type="file" accept=".csv,.xlsx,.txt,.1c" className="sr-only" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }}/><div role="button" tabIndex={0} onClick={() => fileRef.current?.click()} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileRef.current?.click(); } }} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={`flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-[6px] border border-dashed px-4 py-5 text-center transition-colors focus-visible:outline-2 focus-visible:outline-[color:var(--accent)] ${dragging ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)]" : "border-[color:var(--border)] bg-[color:var(--surface-subtle)] hover:border-[color:var(--accent)]"}`}><CloudUpload size={24} className="text-[color:var(--accent)]" aria-hidden="true"/><p className="mt-2 text-sm font-medium">{busy ? "Обрабатываем запрос…" : "Перетащите файл или выберите на компьютере"}</p><ContentText variant="description" tone="muted" className="mt-1">Файл проверяется перед импортом.</ContentText></div></section>
        {preview && <section className="min-w-0 border-t border-[color:var(--border)] pt-4"><ContentHeading level={2}>Сопоставление колонок</ContentHeading><ContentText variant="description" tone="muted" className="mt-1">Проверьте предложенные поля. Для знаковой суммы укажите тот же столбец в «Сумма» и «Знаковая сумма».</ContentText><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{mappingFields.map(field => <Select density="form" key={field.key} label={`${field.label}${field.required ? " *" : ""}`} size="lg" value={mapping[field.key] ?? ""} options={[{ value: "", label: "Не сопоставлено" }, ...preview.data.columns.map(column => ({ value: column, label: column }))]} onChange={event => setMapping(current => ({ ...current, [field.key]: event.target.value }))}/>)}</div><div className="mt-4 max-w-full overflow-x-auto border border-[color:var(--border)]"><Table className="min-w-full"><TableHeader><TableRow>{preview.data.columns.map((column, index) => <TableHead key={`${column}-${index}`} className="whitespace-nowrap">{column}</TableHead>)}</TableRow></TableHeader><TableBody>{preview.data.rows.slice(0, 5).map((row, index) => <TableRow key={index}>{row.map((cell, cellIndex) => <TableCell key={cellIndex} className="max-w-48 truncate" title={cell}>{cell}</TableCell>)}</TableRow>)}</TableBody></Table></div><div className="mt-4 flex gap-2"><Button type="button" size="lg" disabled={busy} onClick={() => void saveMapping()}>Запустить импорт</Button><Button type="button" variant="ghost" size="lg" onClick={() => setPreview(null)}>Отмена</Button></div></section>}
        {job?.kind === "import" && processing && <ContentText variant="description" tone="muted" role="status">Импорт обрабатывается: {Math.round(job.progress * 100)}%. Результат появится после завершения.</ContentText>}
        {report && <section className="border-t border-[color:var(--border)] pt-4"><ContentHeading level={2}>Результат импорта</ContentHeading><div className="mt-3 flex flex-wrap gap-5 text-[13px]"><span>Добавлено: <b className="tabular-nums">{report.added}</b></span><span>Дубли: <b className="tabular-nums">{report.duplicates}</b></span><span>Ошибки: <b className="tabular-nums">{report.errors.length}</b></span></div>{report.errors.length > 0 && <ul className="mt-3 space-y-1 border-t border-[color:var(--border)] pt-3 text-[12px] text-[color:var(--text-secondary)]">{report.errors.slice(0, 10).map((issue, index) => <li key={index}>Строка {issue.row ?? "—"}: {issue.message ?? issue.code ?? "Ошибка обработки"}</li>)}</ul>}</section>}
      </div>}
      {activeWizard === "onec" && companyId && <div className="space-y-4"><OneCConnection companyId={companyId} companyINN={selectedCompany?.inn ?? null} sources={sources} onOpenBankImport={() => setActiveWizard("bank")} onChanged={() => { if (activeCompanyId.current !== companyId) return; void reload(companyId).catch(cause => setError(errorMessage(cause))); void reloadCompanies().catch(cause => setError(errorMessage(cause))); plans.refresh(); }} />{oneCPlans.length > 0 && <details className="text-sm"><summary className="cursor-pointer font-medium">Счета из 1С · {oneCPlans.length}</summary><div className="mt-3 space-y-3">{oneCPlans.slice(0, 20).map(event => <div key={event.id} className="border-t border-[color:var(--border)] pt-3"><p>{event.title} · {event.direction === "in" ? "К получению" : "К оплате"} · сумма {event.total_kopecks == null ? "Неизвестна" : rubles(event.total_kopecks / 100)} · остаток {event.remaining_kopecks == null ? "Неизвестен" : rubles(event.remaining_kopecks / 100)}</p><p className="text-[color:var(--text-secondary)]">Оплачено {event.paid_kopecks == null ? "неизвестно" : rubles(event.paid_kopecks / 100)} · {event.due_date ?? "Срок неизвестен"} · {paymentStatus(event.payment_status || event.status)}{!event.forecast_eligible ? " · вне точечного прогноза" : ""}</p></div>)}</div></details>}</div>}
      {activeWizard === "sheets" && companyId && <><ContentText variant="description" tone="muted" className="mb-3">Укажите доступную таблицу, затем проверьте столбцы перед импортом.</ContentText>{capabilities.data?.sandbox && <ContentText variant="description" tone="muted" role="status" className="mb-3">Деморежим: ответы Google Sheets синтетические. Реальные ключи не вводите.</ContentText>}<SheetConnection key={`sheets-${companyId}`} companyId={companyId} onChanged={() => { void reload(companyId).catch(cause => setError(errorMessage(cause))); }} /></>}
      {activeWizard === "marketplaces" && companyId && <><ContentText variant="description" tone="muted" className="mb-3">Отчёты площадок не заменяют банковскую выписку.</ContentText>{capabilities.data?.sandbox && <ContentText variant="description" tone="muted" role="status" className="mb-3">Деморежим: ответы Wildberries и Ozon синтетические. Реальные ключи не вводите.</ContentText>}<MarketplaceConnections key={`marketplace-${companyId}`} companyId={companyId} onChanged={() => { void reload(companyId).catch(cause => setError(errorMessage(cause))); }} /></>}
      {activeWizard === "fns" && companyId && <div className="space-y-4"><div className="flex flex-wrap gap-2"><Button variant={fnsSection === "registry" ? "default" : "outline"} onClick={() => setFnsSection("registry")}>Документы ЕГРЮЛ/ЕГРИП</Button><Button variant={fnsSection === "snapshot" ? "default" : "outline"} onClick={() => setFnsSection("snapshot")}>Открытые данные</Button><Button variant={fnsSection === "company" ? "default" : "outline"} onClick={() => setFnsSection("company")}><ShieldCheck aria-hidden="true"/>Проверка реквизитов</Button></div>
        {fnsSection === "registry" && <RegistryDocuments key={companyId} companyId={companyId} companyINN={selectedCompany?.inn ?? null} />}
        {fnsSection === "snapshot" && <FNSOpenData key={`fns-${companyId}`} companyId={companyId} />}
        {fnsSection === "company" && <section className="space-y-3"><ContentHeading level={2}>Проверка реквизитов компании</ContentHeading><ContentText variant="description" tone="muted">DaData использует ключ оператора сервиса. Банковские операции и остатки эта проверка не создаёт.</ContentText>{capabilities.data?.sandbox && <ContentText variant="description" tone="muted">Демонстрационный режим: ответы DaData синтетические. Реальные ключи не вводите.</ContentText>}<Input label="Название подключения" value={title} onChange={event => setTitle(event.target.value)} placeholder={sourceNames[kind]} inputSize="sm"/>{!selectedCompany?.inn && <ContentText variant="description" tone="muted">Добавьте ИНН в настройках компании, чтобы подключить проверку.</ContentText>}<Button type="button" disabled={busy || !selectedCompany?.inn} onClick={() => void connect()}>{busy ? "Подключаем…" : "Подключить DaData"}</Button></section>}
      </div>}
    </Dialog>
    {pollError && <div role="alert" className="space-y-2 text-sm"><p>Проверка задания приостановлена: {pollError} Задание может продолжать выполняться на сервере.</p><Button variant="outline" onClick={() => setPollError("")}>Повторить проверку задания</Button></div>}
    {editingSource && <Dialog open title="Название источника" onClose={() => { if (!busy) setEditingSource(null); }} dismissDisabled={busy}><form className="space-y-4" onSubmit={e => { e.preventDefault(); void updateSource(editingSource, { title: sourceTitle.trim() }); }}><Input label="Название" required maxLength={300} value={sourceTitle} onChange={e => setSourceTitle(e.target.value)} />{error && <p role="alert">{error}</p>}<Button type="submit" loading={busy} disabled={!sourceTitle.trim()}>Сохранить</Button></form></Dialog>}
    <ConfirmDialog open={!!deletingSource} title="Удалить источник?" description={deletingSource?.title} loading={busy} onCancel={() => { if (!busy) setDeletingSource(null); }} onConfirm={() => void deleteSource()}><Checkbox label="Сохранить импортированные операции" checked={keepData} onChange={e => setKeepData(e.target.checked)} />{!keepData && <ContentText variant="body" className="mt-2">Связанные операции будут удалены. Прогноз изменится.</ContentText>}{error && <p role="alert">{error}</p>}</ConfirmDialog>
    {job && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><div className="flex justify-between gap-3 text-[13px]"><ContentHeading level={2} >{job.kind === "import" ? "Импорт выписки" : "Синхронизация"}</ContentHeading><span className="text-[color:var(--text-secondary)]">{job.status === "queued" ? "В очереди" : job.status === "running" ? "Обработка" : job.status === "done" ? "Готово" : "Ошибка"}</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[color:var(--surface-subtle)]"><div className="h-full bg-[color:var(--accent)] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, job.progress * 100))}%` }}/></div><ContentText variant="description" tone="muted" className="mt-1 tabular-nums">{Math.round(job.progress * 100)}% · статус задания из API</ContentText>{job.error && <ContentText variant="meta" tone="danger" className="mt-2">{job.error}</ContentText>}</section>}
    <section className="min-w-0 space-y-3"><ContentHeading level={2}>История импортов</ContentHeading><Table className="min-w-[620px]"><TableHeader><TableRow><TableHead>Дата</TableHead><TableHead>Источник</TableHead><TableHead numeric>Добавлено</TableHead><TableHead numeric>Дубли</TableHead><TableHead numeric>Ошибки</TableHead><TableHead>Статус</TableHead><TableHead aria-label="Подробности" /></TableRow></TableHeader><TableBody>{imports.length ? imports.map(item => <TableRow key={item.id}><TableCell>{formatDate(item.started_at)}</TableCell><TableCell>{item.source?.kind ? sourceNames[item.source.kind as SourceKind] ?? item.source.kind : sources.find(source => source.id === item.source_id)?.title ?? "Источник удалён"}</TableCell><TableCell numeric>{item.added}</TableCell><TableCell numeric>{item.duplicates}</TableCell><TableCell numeric>{item.errors?.length ?? 0}</TableCell><TableCell>{importStatusNames[item.status] ?? item.status}</TableCell><TableCell><Button variant="ghost" size="sm" onClick={() => { setActiveWizard("bank"); void selectReport(item.id); }}>Подробнее</Button></TableCell></TableRow>) : <TableRow><TableCell colSpan={7} tone="muted">Импортов пока нет.</TableCell></TableRow>}</TableBody></Table></section>
  </div>;
}
