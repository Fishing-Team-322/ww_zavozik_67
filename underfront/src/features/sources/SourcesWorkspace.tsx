"use client";

import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import Link from "next/link";
import { OneCConnection } from "./OneCConnection";
import { RegistryDocuments } from "./RegistryDocuments";
import { MarketplaceConnections } from "./MarketplaceConnections";
import { FNSOpenData } from "./FNSOpenData";
import { IntegrationCatalog } from "./IntegrationCatalog";
import { SheetConnection } from "./SheetConnection";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { api } from "@/src/shared/api";
import { Dialog, ConfirmDialog, Checkbox, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import type { Schemas } from "@/src/shared/api";
import { rubles } from "@/src/entities/forecast";
import { CloudUpload, RefreshCw, Plus, CheckCircle2, AlertCircle } from "lucide-react";
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
  const [sources, setSources] = useState<DataSource[]>([]);
  const [imports, setImports] = useState<ImportReport[]>([]);
  const [loading, setLoading] = useState(!!companyId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<{ uploadId: string; data: UploadPreview } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const kind = "fns" as const;
  const [title, setTitle] = useState("");
  const [editingSource, setEditingSource] = useState<DataSource | null>(null);
  const [sourceTitle, setSourceTitle] = useState("");
  const [deletingSource, setDeletingSource] = useState<DataSource | null>(null);
  const [keepData, setKeepData] = useState(true);
  const [pollError, setPollError] = useState("");
  const refreshPlans = plans.refresh;
  const processing = job?.status === "queued" || job?.status === "running";

  useEffect(() => { activeCompanyId.current = companyId; }, [companyId]);

  const reload = useCallback(async (id: string) => {
    const [nextSources, nextImports] = await Promise.all([sourceApi.list(id), sourceApi.imports(id)]);
    if (activeCompanyId.current === id) { setSources(nextSources); setImports(nextImports); }
  }, []);

  useEffect(() => {
    if (!companyId) return;
    let cancelled = false;
    Promise.all([sourceApi.list(companyId), sourceApi.imports(companyId)])
      .then(([nextSources, nextImports]) => { if (!cancelled) { setSources(nextSources); setImports(nextImports); } })
      .catch(cause => { if (!cancelled) setError(errorMessage(cause)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [companyId]);

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
          await reloadCompanies(companyId);
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
    if (busy || !companyId) return;
    setBusy(true); setError("");
    try { await sourceApi.update(source.id, input); await reload(companyId); setEditingSource(null); setNotice("Источник обновлён."); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function deleteSource() {
    if (busy || !deletingSource || !companyId) return;
    setBusy(true); setError("");
    try { await sourceApi.remove(deletingSource.id, keepData); await reload(companyId); await reloadCompanies(companyId); setDeletingSource(null); setNotice("Источник удалён."); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function upload(file: File) {
    if (/\.pdf$/i.test(file.name)) { setError("PDF ЕГРЮЛ/ЕГРИП загрузите в разделе «Документы ФНС» ниже. Для банковских операций нужны CSV, XLSX или файл 1С. Поддержка произвольных банковских PDF отсутствует."); document.getElementById("registry-documents")?.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
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
      const config: Record<string, unknown> = {};
      const input: CreateSourceInput = { kind, title: title.trim() || sourceNames[kind], config };
      await sourceApi.create(requestedCompanyId, input);
      await reload(requestedCompanyId);
      if (activeCompanyId.current !== requestedCompanyId) return;
      setConnectOpen(false);
      setNotice("Настройки источника сохранены. Проверьте соединение и запустите синхронизацию.");
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
        if (requestedCompanyId) await reload(requestedCompanyId);
        if (activeCompanyId.current === requestedCompanyId) setNotice(result.message);
      } else {
        const nextJob = await sourceApi.sync(source.id);
        if (activeCompanyId.current !== requestedCompanyId) return;
        setJob(nextJob);
        setNotice(`Синхронизация «${source.title}» поставлена в очередь.`);
      }
    } catch (cause) { setError(errorMessage(cause)); if (requestedCompanyId) void reload(requestedCompanyId).catch(() => {}); }
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
    {companyId && <IntegrationCatalog key={`catalog-${companyId}`} companyId={companyId} />}
    {companyId && <RegistryDocuments key={companyId} companyId={companyId} companyINN={selectedCompany?.inn ?? null} />}
    {companyId && <MarketplaceConnections key={`marketplace-${companyId}`} companyId={companyId} onChanged={() => { void reload(companyId).catch(cause => setError(errorMessage(cause))); }} />}
    {companyId && <FNSOpenData key={`fns-${companyId}`} companyId={companyId} />}
    {companyId && <SheetConnection key={`sheets-${companyId}`} companyId={companyId} onChanged={() => { void reload(companyId).catch(cause => setError(errorMessage(cause))); }} />}
    {error && <div role="alert" className="flex items-start gap-2 border-l-2 border-[color:var(--danger)] bg-[color:var(--surface-subtle)] px-3 py-2 text-[13px]"><AlertCircle size={16} className="mt-0.5 shrink-0"/>{error}<Button variant="outline" size="sm" disabled={busy || !companyId} onClick={async () => { if (!companyId) return; setError(""); try { await reload(companyId); } catch (cause) { setError(errorMessage(cause)); } }}>Обновить список</Button></div>}
    {companyId && <OneCConnection companyId={companyId} companyINN={selectedCompany?.inn ?? null} sources={sources} onChanged={() => { void reload(companyId).catch(cause => setError(errorMessage(cause))); void reloadCompanies(companyId).catch(cause => setError(errorMessage(cause))); plans.refresh(); }} />}
    {oneCPlans.length > 0 && <section className="space-y-3"><h2 className="text-[16px] font-semibold">Счета из 1С</h2>{oneCPlans.slice(0, 20).map(event => <div key={event.id} className="border-t border-[color:var(--border)] pt-3 text-sm"><p>{event.title} · {event.direction === "in" ? "К получению" : "К оплате"} · сумма {event.total_kopecks == null ? "Неизвестна" : rubles(event.total_kopecks / 100)} · остаток {event.remaining_kopecks == null ? "Неизвестен" : rubles(event.remaining_kopecks / 100)}</p><p className="text-[color:var(--text-secondary)]">Оплачено {event.paid_kopecks == null ? "неизвестно" : rubles(event.paid_kopecks / 100)} · {event.due_date ?? "Срок неизвестен"} · {paymentStatus(event.payment_status || event.status)}{!event.forecast_eligible ? " · вне точечного прогноза" : ""}</p></div>)}</section>}
    {notice && <p role="status" className="flex items-center gap-2 text-[12px] text-[color:var(--text-secondary)]"><CheckCircle2 size={15} className="text-[color:var(--accent)]"/>{notice}</p>}
    {connectOpen && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4 sm:p-5"><h2 className="mb-4 text-[16px] font-semibold">Новое подключение</h2><div className="grid gap-4 sm:grid-cols-2"><p className="text-sm">DaData · сведения об организации</p><Input label="Название подключения" value={title} onChange={event => setTitle(event.target.value)} placeholder={sourceNames[kind]} className="h-8"/></div>
      {kind === "fns" && <p className="mt-3 text-[12px] text-[color:var(--text-secondary)]">{selectedCompany?.inn ? "Ключ DaData настраивает оператор сервиса." : "У выбранной компании нет ИНН. Для проверки ФНС добавьте ИНН в реквизитах компании."}</p>}
      <div className="mt-4 flex gap-2"><Button type="button" size="lg" disabled={busy || !selectedCompany?.inn} onClick={() => void connect()}>{busy ? "Подключаем…" : "Подключить"}</Button><Button type="button" size="lg" variant="ghost" onClick={() => setConnectOpen(false)}>Отмена</Button></div>
    </section>}
    <section className="space-y-3"><div className="flex items-center justify-between"><h2 className="text-[16px] font-semibold">Подключённые источники</h2><span className="text-[12px] text-[color:var(--text-secondary)]">{sources.length}</span></div>{loading ? <p className="text-[13px] text-[color:var(--text-secondary)]">Загружаем источники…</p> : sources.length ? <div className="grid gap-3 lg:grid-cols-2">{sources.map(source => <article key={source.id} className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 className="truncate text-[13px] font-semibold">{source.title}</h3><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">{sourceNames[source.kind] ?? source.kind}{source.data_mode === "mock" ? " · ДЕМОНСТРАЦИЯ / MOCK" : ""}</p></div><span className="rounded-[4px] bg-[color:var(--surface-subtle)] px-2 py-0.5 text-[11px] text-[color:var(--text-secondary)]">{source.enabled ? ({ ok: "Готово", error: "Ошибка", pending: "Ожидает проверки", syncing: "Синхронизация" } as Record<string, string>)[source.status] ?? source.status : "Отключён"}</span></div><div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-t border-[color:var(--border)] pt-3 text-[12px] text-[color:var(--text-secondary)]"><span>{["wb", "ozon"].includes(source.kind) ? "Строк отчёта" : "Операций"}: <b className="font-medium tabular-nums text-[color:var(--text-primary)]">{source.records}</b></span><span>Последняя синхронизация: {formatDate(source.last_synced_at)}</span></div>{source.error && <p className="mt-2 text-[12px] text-[color:var(--danger)]">{source.error}</p>}{source.enabled && ["gsheets", "onec_odata", "fns", "wb", "ozon"].includes(source.kind) && <div className="mt-3 flex gap-2"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void sourceAction(source, "test")}>Проверить</Button><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void sourceAction(source, "sync")}><RefreshCw aria-hidden="true"/>Синхронизировать</Button></div>}<div className="mt-3 flex flex-wrap gap-2"><Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => { setSourceTitle(source.title); setEditingSource(source); }}>Название</Button><Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => void updateSource(source, { enabled: !source.enabled })}>{source.enabled ? "Отключить" : "Включить"}</Button><Button variant="ghost" size="sm" disabled={busy || processing} onClick={() => { setKeepData(true); setDeletingSource(source); }}>Удалить</Button></div></article>)}</div> : <p className="border-y border-[color:var(--border)] py-4 text-[13px] text-[color:var(--text-secondary)]">Источников пока нет. Загрузите выписку или добавьте подключение.</p>}</section>
    <section className="space-y-3"><div><h2 className="text-[16px] font-semibold">Банковские операции · импорт выписки</h2><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">CSV, XLSX или 1CClientBankExchange · до 4 МиБ</p></div><input ref={fileRef} type="file" accept=".csv,.xlsx,.txt,.1c" className="sr-only" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); }}/><div role="button" tabIndex={0} onClick={() => fileRef.current?.click()} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileRef.current?.click(); } }} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={`flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-[6px] border border-dashed px-4 py-4 text-center transition-colors focus-visible:outline-2 focus-visible:outline-[color:var(--accent)] ${dragging ? "border-[color:var(--accent)] bg-[color:var(--accent-soft)]" : "border-[color:var(--border)] bg-[color:var(--surface-subtle)] hover:border-[color:var(--accent)]"}`}><CloudUpload size={23} className="text-[color:var(--text-secondary)]" aria-hidden="true"/><p className="mt-2 text-[13px] font-medium">{busy ? "Обрабатываем запрос…" : "Перетащите файл сюда или нажмите для выбора"}</p><p className="mt-1 text-[11px] text-[color:var(--text-secondary)]">Загрузка файла запускает импорт только после проверки колонок, если она потребуется.</p></div></section>
    {preview && <section className="min-w-0 rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><h2 className="text-[16px] font-semibold">Сопоставление колонок</h2><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]">Проверьте предложенные поля. Для знаковой суммы укажите тот же столбец в «Сумма» и «Знаковая сумма».</p><div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{mappingFields.map(field => <Select key={field.key} label={`${field.label}${field.required ? " *" : ""}`} size="lg" value={mapping[field.key] ?? ""} options={[{ value: "", label: "Не сопоставлено" }, ...preview.data.columns.map(column => ({ value: column, label: column }))]} onChange={event => setMapping(current => ({ ...current, [field.key]: event.target.value }))}/>)}</div><div className="mt-4 max-w-full overflow-x-auto border border-[color:var(--border)]"><Table unstyled className="min-w-full text-left text-[12px]"><TableHeader unstyled className="bg-[color:var(--surface-subtle)]"><TableRow unstyled>{preview.data.columns.map((column, index) => <TableHead unstyled key={`${column}-${index}`} className="whitespace-nowrap border-r border-[color:var(--border)] px-2 py-1.5 font-medium">{column}</TableHead>)}</TableRow></TableHeader><TableBody>{preview.data.rows.slice(0, 5).map((row, index) => <TableRow unstyled key={index} className="border-t border-[color:var(--border)]">{row.map((cell, cellIndex) => <TableCell unstyled key={cellIndex} className="max-w-48 truncate border-r border-[color:var(--border)] px-2 py-1.5" title={cell}>{cell}</TableCell>)}</TableRow>)}</TableBody></Table></div><div className="mt-4 flex gap-2"><Button type="button" size="lg" disabled={busy} onClick={() => void saveMapping()}>Запустить импорт</Button><Button type="button" variant="ghost" size="lg" onClick={() => setPreview(null)}>Отмена</Button></div></section>}
    {pollError && <div role="alert" className="space-y-2 text-sm"><p>Проверка задания приостановлена: {pollError} Задание может продолжать выполняться на сервере.</p><Button variant="outline" onClick={() => setPollError("")}>Повторить проверку задания</Button></div>}
    {editingSource && <Dialog open title="Название источника" onClose={() => { if (!busy) setEditingSource(null); }} dismissDisabled={busy}><form className="space-y-4" onSubmit={e => { e.preventDefault(); void updateSource(editingSource, { title: sourceTitle.trim() }); }}><Input label="Название" required maxLength={300} value={sourceTitle} onChange={e => setSourceTitle(e.target.value)} />{error && <p role="alert">{error}</p>}<Button type="submit" loading={busy} disabled={!sourceTitle.trim()}>Сохранить</Button></form></Dialog>}
    <ConfirmDialog open={!!deletingSource} title="Удалить источник?" description={deletingSource?.title} loading={busy} onCancel={() => { if (!busy) setDeletingSource(null); }} onConfirm={() => void deleteSource()}><Checkbox label="Сохранить импортированные операции" checked={keepData} onChange={e => setKeepData(e.target.checked)} />{!keepData && <p className="mt-2 text-sm">Связанные операции будут удалены. Прогноз изменится.</p>}{error && <p role="alert">{error}</p>}</ConfirmDialog>
    {job && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><div className="flex justify-between gap-3 text-[13px]"><h2 className="font-semibold">{job.kind === "import" ? "Импорт выписки" : "Синхронизация"}</h2><span className="text-[color:var(--text-secondary)]">{job.status === "queued" ? "В очереди" : job.status === "running" ? "Обработка" : job.status === "done" ? "Готово" : "Ошибка"}</span></div><div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[color:var(--surface-subtle)]"><div className="h-full bg-[color:var(--accent)] transition-[width]" style={{ width: `${Math.max(0, Math.min(100, job.progress * 100))}%` }}/></div><p className="mt-1 text-[11px] tabular-nums text-[color:var(--text-secondary)]">{Math.round(job.progress * 100)}% · статус задания из API</p>{job.error && <p className="mt-2 text-[12px] text-[color:var(--danger)]">{job.error}</p>}</section>}
    {report && <section className="rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface)] p-4"><h2 className="text-[16px] font-semibold">Результат импорта</h2><div className="mt-3 flex flex-wrap gap-5 text-[13px]"><span>Добавлено: <b className="tabular-nums">{report.added}</b></span><span>Дубли: <b className="tabular-nums">{report.duplicates}</b></span><span>Ошибки: <b className="tabular-nums">{report.errors.length}</b></span></div>{report.errors.length > 0 && <ul className="mt-3 space-y-1 border-t border-[color:var(--border)] pt-3 text-[12px] text-[color:var(--text-secondary)]">{report.errors.slice(0, 10).map((issue, index) => <li key={index}>Строка {issue.row ?? "—"}: {issue.message ?? issue.code ?? "Ошибка обработки"}</li>)}</ul>}</section>}
    <section className="min-w-0"><h2 className="mb-3 text-[16px] font-semibold">История импортов</h2><div className="max-w-full overflow-x-auto border-y border-[color:var(--border)]"><Table unstyled className="w-full min-w-[620px] text-left text-[12px]"><TableHeader unstyled><TableRow unstyled className="text-[color:var(--text-secondary)]"><TableHead unstyled className="px-2 py-2 font-medium">Дата</TableHead><TableHead unstyled className="px-2 py-2 font-medium">Источник</TableHead><TableHead unstyled className="px-2 py-2 text-right font-medium">Добавлено</TableHead><TableHead unstyled className="px-2 py-2 text-right font-medium">Дубли</TableHead><TableHead unstyled className="px-2 py-2 text-right font-medium">Ошибки</TableHead></TableRow></TableHeader><TableBody>{imports.length ? imports.map(item => <TableRow unstyled key={item.id} className="border-t border-[color:var(--border)] hover:bg-[color:var(--surface-subtle)]"><TableCell unstyled className="px-2 py-2">{formatDate(item.started_at)}</TableCell><TableCell unstyled className="px-2 py-2">{item.source?.kind ? sourceNames[item.source.kind as SourceKind] ?? item.source.kind : item.source_id}</TableCell><TableCell unstyled className="px-2 py-2 text-right tabular-nums">{item.added}</TableCell><TableCell unstyled className="px-2 py-2 text-right tabular-nums">{item.duplicates}</TableCell><TableCell unstyled className="px-2 py-2 text-right tabular-nums">{item.errors?.length ?? 0}</TableCell></TableRow>) : <TableRow unstyled><TableCell unstyled colSpan={5} className="px-2 py-4 text-[color:var(--text-secondary)]">Импортов пока нет.</TableCell></TableRow>}</TableBody></Table></div></section>
    {imports.length > 0 && <div className="max-w-sm"><Select label="Посмотреть подробности прошлого импорта" size="lg" value={report?.id ?? ""} options={[{ value: "", label: "Выберите импорт" }, ...imports.map(item => ({ value: item.id, label: `${formatDate(item.started_at)} · ${item.added} добавлено` }))]} onChange={async event => { if (!event.target.value) { setReport(null); return; } try { setReport(await sourceApi.import(event.target.value)); } catch (cause) { setError(errorMessage(cause)); } }}/></div>}
  </div>;
}
