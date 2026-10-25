import { ApiError, type ApiClient, type Company, type Forecast, type Schemas } from "@/src/shared/api";
import { actualBalances, evaluateForecast } from "./metrics";
import { dayOffset, operationsCSV, sha256 } from "./dataset";
import type { CheckpointLog, CheckpointReport, ControlData, ControlSource } from "./types";

type Client = Pick<ApiClient, "request">;
export type RunOptions = { mode: "holdout" | "forecast"; horizon: number; reserve: number; cutoff: string };
export type RunCallbacks = { log: (entry: CheckpointLog) => void; stage: (message: string) => void; created: (company: Company) => void };

const pause = (signal: AbortSignal, milliseconds: number) => new Promise<void>((resolve, reject) => {
  if (signal.aborted) { reject(signal.reason); return; }
  const abort = () => { clearTimeout(timer); reject(signal.reason); };
  const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, milliseconds);
  signal.addEventListener("abort", abort, { once: true });
});

export function splitControlData(data: ControlData, options: RunOptions) {
  if (![7, 14, 30].includes(options.horizon) || !Number.isFinite(options.reserve) || options.reserve < 0 || options.reserve > 1e13) throw new Error("Проверьте горизонт и резерв.");
  const cutoff = options.mode === "holdout" ? options.cutoff : data.to;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff) || cutoff < data.from || cutoff > data.to) throw new Error("Дата отсечения должна находиться внутри истории.");
  const training = data.operations.filter(op => op.date <= cutoff);
  if (!training.length) throw new Error("До даты отсечения нет операций.");
  const asOf = training.at(-1)!.date;
  if (options.mode === "holdout" && dayOffset(asOf, options.horizon) > data.to) throw new Error("После даты отсечения недостаточно данных для выбранного горизонта.");
  const withheld = data.operations.filter(op => op.date > asOf);
  if (options.mode === "holdout" && !withheld.length) throw new Error("Для ретроспективной проверки нужны операции после даты отсечения.");
  if (!training.some(op => op.balance !== null)) throw new Error("В истории нет подтверждённого остатка.");
  const trainingCSV = operationsCSV(training), withheldCSV = operationsCSV(withheld);
  if (new TextEncoder().encode(trainingCSV).byteLength > 4 * 1024 * 1024) throw new Error("Выбранная история превышает лимит импорта 4 МиБ. Сократите период или выберите отдельную выписку.");
  return { training, withheld, asOf, trainingCSV, withheldCSV };
}

export async function runCheckpoint(client: Client, source: ControlSource, data: ControlData, options: RunOptions, signal: AbortSignal, callbacks: RunCallbacks) {
  const split = splitControlData(data, options);
  const logs: CheckpointLog[] = [];
  const started = performance.now(), deadline = Date.now() + 10 * 60_000;
  const log = (event: string, message: string, details?: Record<string, unknown>) => {
    const entry: CheckpointLog = { at: new Date().toISOString(), event, message, elapsed_ms: Math.round(performance.now() - started), ...(details ? { details } : {}) };
    logs.push(entry); callbacks.log(entry);
  };
  callbacks.stage("Фиксируем входные данные и период проверки…");
  const [fileHash, trainingHash, withheldHash] = await Promise.all([sha256(source.file), sha256(split.trainingCSV), sha256(split.withheldCSV)]);
  log("input_prepared", "Файл прочитан, компания выбрана, точные повторы исключены.", { file_sha256: fileHash, selected_company: data.company.key, rows: data.operations.length, duplicates: data.duplicates });
  log("protocol_frozen", options.mode === "holdout" ? "История и отложенный период разделены до отправки в API. Будущие строки в импорт не входят." : "В API отправляется вся история; будущий факт не предоставлен.", { as_of: split.asOf, horizon: options.horizon, training_rows: split.training.length, withheld_rows: split.withheld.length, training_sha256: trainingHash, withheld_sha256: withheldHash, reserve: options.reserve });
  const companyName = `Контроль · ${data.company.name} · ${new Date().toISOString().slice(0, 19)}`.slice(0, 200);
  callbacks.stage("Создаём отдельную контрольную компанию…");
  const company = await client.request<Company>("/v1/companies", { method: "POST", signal, json: { name: companyName, legal_form: data.company.legalForm, industry: data.company.industry.slice(0, 100) || "Контрольный набор", reserve: options.reserve } });
  callbacks.created(company);
  const base = `/v1/companies/${company.id}`;
  log("workspace_created", "Создана отдельная компания. Платежи рабочей компании не изменяются.", { company_id: company.id });
  const form = new FormData(); form.append("file", new Blob([split.trainingCSV], { type: "text/csv" }), "checkpoint-history.csv");
  callbacks.stage("Импортируем историю и ожидаем категоризацию…");
  const upload = await client.request<Schemas["Job"] | { needs_mapping: boolean }>(`${base}/uploads`, { method: "POST", form, signal });
  if (!("id" in upload)) throw new Error("API запросил сопоставление колонок нормализованного CSV. Импорт остановлен.");
  log("import_queued", "Сервер принял только историю до даты отсечения.", { job_id: upload.id });
  let job = upload, previousStatus = "";
  while (job.status !== "done" && job.status !== "failed") {
    if (Date.now() > deadline) throw new Error("Превышено время ожидания импорта. Контрольная компания сохранена; проверьте её задания.");
    if (job.status !== previousStatus) { log("import_status", `Импорт: ${job.status === "running" ? "выполняется" : "в очереди"}.`, { status: job.status }); previousStatus = job.status; }
    await pause(signal, 1500);
    job = await client.request<Schemas["Job"]>(`/v1/jobs/${upload.id}`, { signal });
  }
  if (job.status === "failed") throw new Error(job.error || "Импорт завершился ошибкой.");
  if (!job.result_ref || !/^\/v1\/imports\/[0-9a-f-]{36}$/i.test(job.result_ref)) throw new Error("API не вернул подтверждённый отчёт импорта.");
  const imported = await client.request<{ added: number; duplicates: number; errors: unknown[] }>(job.result_ref, { signal });
  log("import_completed", "Получен отчёт завершённого импорта.", { added: imported.added, duplicates: imported.duplicates, rejected: imported.errors?.length ?? 0 });
  if (imported.errors?.length) throw new Error(`Сервер отклонил ${imported.errors.length} строк. Проверка остановлена: неполную историю нельзя выдать за исходный набор.`);
  callbacks.stage("Ожидаем пересчёт прогноза на сервере…");
  let lastRevision = "";
  while (true) {
    const updates = await client.request<Schemas["CompanyUpdates"]>(`${base}/updates`, { signal });
    if (updates.last_job_error) throw new Error(`Пересчёт: ${updates.last_job_error}`);
    const revision = `${updates.data_revision}:${updates.forecast_revision}:${updates.pending_jobs}`;
    if (revision !== lastRevision) { log("revision_observed", "Проверено состояние пересчёта.", { data_revision: updates.data_revision, forecast_revision: updates.forecast_revision, pending_jobs: updates.pending_jobs }); lastRevision = revision; }
    if (updates.pending_jobs === 0 && updates.forecast_revision === updates.data_revision) break;
    if (Date.now() > deadline) throw new Error("Превышено время ожидания прогноза. Контрольная компания сохранена.");
    await pause(signal, 1500);
  }
  const forecast = await client.request<Forecast>(`${base}/forecast?horizon=${options.horizon}`, { signal });
  if (forecast.as_of !== split.asOf || forecast.points.length !== options.horizon || forecast.points.some((point, index) => point.date !== dayOffset(split.asOf, index + 1) || ![point.p10, point.p50, point.p90].every(Number.isFinite) || point.p10 > point.p50 || point.p50 > point.p90)) throw new Error("Период или границы прогноза не совпали с зафиксированным протоколом. Результат не принят.");
  log("forecast_received", "Получен и проверен реальный ответ прогноза: даты, горизонт и порядок квантилей.", { model: forecast.model_used, model_version: forecast.model_version, fallback_used: forecast.fallback_used, low_confidence: forecast.low_confidence, points: forecast.points.length, forecast_sha256: await sha256(JSON.stringify(forecast)) });
  callbacks.stage("Сопоставляем прогноз с отложенным фактом…");
  const byMethod: Record<string, number> = {};
  let cursor: string | null = null, total = 0;
  do {
    const page: Schemas["OperationPage"] = await client.request(`${base}/operations?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, { signal });
    for (const operation of page.items) { const method = operation.category_method || "unknown"; byMethod[method] = (byMethod[method] ?? 0) + 1; total++; }
    cursor = page.next_cursor;
    if (total > 10000) throw new Error("Неожиданный объём данных контрольной компании.");
  } while (cursor);
  log("classification_observed", "Считаны фактические результаты категоризации. Независимой эталонной разметки в выписке нет.", { operations: total, by_method: byMethod });
  const metrics = evaluateForecast(forecast, actualBalances(data.operations), options.reserve, options.mode === "holdout");
  log("metrics_calculated", options.mode === "holdout" ? "Оценки рассчитаны по датам, где факт подтверждён сверкой остатков. Неизвестные дни исключены." : "Метрики ошибки не рассчитаны: будущий факт отсутствует.", { samples: metrics.samples, excluded: metrics.excluded, risk_decision: "p50 < reserve", category_ground_truth: false });
  const report: CheckpointReport = { version: 1, id: crypto.randomUUID(), created_at: new Date().toISOString(), company_id: company.id, company_name: company.name, dataset_company: data.company.key, mode: options.mode, horizon: options.horizon, reserve: options.reserve, cutoff: split.asOf,
    input: { filename: source.file.name, file_sha256: fileHash, training_sha256: trainingHash, withheld_sha256: withheldHash, training_rows: split.training.length, withheld_rows: split.withheld.length, duplicates: data.duplicates, from: data.from, to: data.to }, forecast, metrics, logs,
    classification: { total, by_method: byMethod, reason: "Нет независимых эталонных категорий для сопоставления с каждой операцией. Категории модели не используются как собственный эталон." } };
  callbacks.stage("Расчёт завершён.");
  return { report, trainingCSV: split.trainingCSV, withheldCSV: split.withheldCSV };
}

export function checkpointReports(data: Record<string, unknown>): CheckpointReport[] {
  if (!Array.isArray(data.checkpoint_reports)) return [];
  return data.checkpoint_reports.filter((value): value is CheckpointReport => !!value && typeof value === "object" && value.version === 1 && typeof value.id === "string" && typeof value.company_id === "string" && Array.isArray(value.forecast?.points) && Array.isArray(value.logs) && Array.isArray(value.metrics?.points)).slice(0, 3);
}

/** Optimistic merge preserves unrelated workspace data and concurrent edits. */
export async function saveCheckpointReport(client: Client, workspace: string, report: CheckpointReport, signal: AbortSignal) {
  for (let attempt = 0; attempt < 3; attempt++) {
    const state = await client.request<Schemas["CompanyState"]>(`/v1/companies/${workspace}/state`, { signal });
    const reports = [report, ...checkpointReports(state.data).filter(value => value.id !== report.id)].slice(0, 3);
    try { await client.request(`/v1/companies/${workspace}/state`, { method: "PUT", signal, json: { expected_version: state.version, data: { ...state.data, checkpoint_reports: reports } } }); return; }
    catch (error) { if (!(error instanceof ApiError) || error.status !== 409 || attempt === 2) throw error; }
  }
}
