"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, LoaderCircle, Upload } from "lucide-react";
import { api, message, type Company, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { useSession } from "@/src/features/auth";
import { Button, Input, Select, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { CashflowForecastChart } from "@/src/widgets/finance-panels";
import { displayDate, rubles, riskProbabilityText, gapAmount } from "@/src/entities/forecast";
import { dayOffset, inspectDataset, readControlCompany } from "./model/dataset";
import { checkpointReports, runCheckpoint, saveCheckpointReport, splitControlData, type RunOptions } from "./model/runner";
import { downloadCheckpoint, downloadObservations } from "./model/export";
import type { CheckpointLog, CheckpointReport, ControlData, ControlSource } from "./model/types";

const decimal = (value: number | null, digits = 2) => value === null ? "Недоступно" : value.toLocaleString("ru-RU", { maximumFractionDigits: digits });
const fraction = (value: number | null) => value === null ? "Недоступно" : `${decimal(value * 100, 1)}%`;
const methodName: Record<string, string> = { rule: "Правила", user: "Ручная категория", ml: "Модель", qwen: "Qwen", unknown: "Не указан" };

export function CheckpointWorkspace() {
  const { company, reload, selectCompany } = useSession();
  const router = useRouter();
  const state = useApiResource<Schemas["CompanyState"]>(company ? `/v1/companies/${company.id}/state` : null);
  const [source, setSource] = useState<ControlSource | null>(null);
  const [companyKey, setCompanyKey] = useState("");
  const [data, setData] = useState<ControlData | null>(null);
  const [mode, setMode] = useState<RunOptions["mode"]>("holdout");
  const [horizon, setHorizon] = useState(30), [reserve, setReserve] = useState("0"), [cutoff, setCutoff] = useState("");
  const [inspecting, setInspecting] = useState(false), [reading, setReading] = useState(false), [running, setRunning] = useState(false);
  const [stage, setStage] = useState(""), [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<CheckpointLog[]>([]), [report, setReport] = useState<CheckpointReport | null>(null);
  const [created, setCreated] = useState<Company | null>(null);
  const fileInput = useRef<HTMLInputElement>(null), controller = useRef<AbortController | null>(null), fileGeneration = useRef(0);
  const [inputs, setInputs] = useState<{ reportID: string; trainingCSV: string; withheldCSV: string } | null>(null);
  const readGeneration = useRef(0);
  const reports = checkpointReports(state.data?.data ?? {});
  const busy = inspecting || reading || running;

  useEffect(() => () => { controller.current?.abort(); fileGeneration.current++; readGeneration.current++; }, []);
  async function loadCompany(next: ControlSource, key: string, days: number) {
    const generation = ++readGeneration.current;
    setCompanyKey(key); setReading(true); setData(null); setError(null);
    try {
      const value = await readControlCompany(next, key);
      if (generation === readGeneration.current) { setData(value); setCutoff(dayOffset(value.to, -days)); }
    } catch (cause) { if (generation === readGeneration.current) setError(message(cause)); }
    finally { if (generation === readGeneration.current) setReading(false); }
  }

  async function chooseFile(file?: File) {
    if (!file || running) return;
    const generation = ++fileGeneration.current;
    setInspecting(true); setSource(null); setData(null); setError(null); setReport(null); setCreated(null); setLogs([]); setInputs(null);
    setStage("Читаем структуру файла…");
    try {
      const next = await inspectDataset(file, rows => { if (fileGeneration.current === generation) setStage(`Проверено строк: ${rows.toLocaleString("ru-RU")}…`); });
      if (fileGeneration.current !== generation) return;
      setSource(next); await loadCompany(next, next.companies[0].key, horizon); setStage("");
    } catch (cause) { if (fileGeneration.current === generation) setError(message(cause)); }
    finally { if (fileGeneration.current === generation) setInspecting(false); }
  }

  async function run() {
    if (!source || !data || !company) return;
    const workspace = company.id;
    const options: RunOptions = { mode, horizon, reserve: Number(reserve), cutoff };
    try { splitControlData(data, options); } catch (cause) { setError(message(cause)); return; }
    controller.current?.abort(); const active = new AbortController(); controller.current = active;
    const runStarted = performance.now();
    setRunning(true); setError(null); setReport(null); setLogs([]); setCreated(null); setInputs(null);
    try {
      const result = await runCheckpoint(api, source, data, options, active.signal, { stage: setStage, log: entry => setLogs(current => [...current, entry]), created: setCreated });
      setInputs({ reportID: result.report.id, trainingCSV: result.trainingCSV, withheldCSV: result.withheldCSV });
      try { await saveCheckpointReport(api, workspace, result.report, active.signal); state.refresh(); }
      catch (cause) { result.report.persistence_warning = `Отчёт не сохранён в истории: ${message(cause)} Скачайте результаты перед уходом со страницы.`; }
      setReport(result.report); void reload().catch(() => {});
    } catch (cause) { if (!active.signal.aborted) { const text = message(cause); setError(text); setLogs(current => [...current, { at: new Date().toISOString(), event: "run_failed", elapsed_ms: Math.round(performance.now() - runStarted), message: `Проверка остановлена: ${text}` }]); } }
    finally { if (!active.signal.aborted) setRunning(false); }
  }
  async function openCompany(id: string, path: string) { await reload(); selectCompany(id); router.push(path); }
  const reportInputs = report && inputs?.reportID === report.id ? inputs : undefined;
  return <div className="space-y-5">
    <SectionCard className="space-y-5 p-5">
      <div><ContentHeading level={1}>Проверка контрольного датасета</ContentHeading><ContentText variant="description" tone="muted" className="mt-2">Загрузите выписку, получите прогноз и сохраните расчёт для чек-поинта. CSV может содержать одну выписку или общий набор с несколькими компаниями.</ContentText></div>
      <input ref={fileInput} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Контрольный датасет CSV" disabled={busy} onChange={event => { void chooseFile(event.target.files?.[0]); event.target.value = ""; }} />
      <div onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!busy) void chooseFile(event.dataTransfer.files[0]); }} className="rounded-lg border border-dashed border-[color:var(--border)] bg-[color:var(--surface-subtle)] p-6">
        <div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-center gap-3"><Upload className="shrink-0 text-[color:var(--accent)]" size={23} /><div><p className="text-sm font-medium">{source ? source.file.name : "Перетащите CSV датасета"}</p><p className="mt-1 text-xs text-[color:var(--text-secondary)]">CSV до 80 МиБ · UTF-8 · поля исходного датасета</p></div></div><Button variant="outline" disabled={busy} onClick={() => fileInput.current?.click()}>{source ? "Заменить файл" : "Выбрать файл"}</Button></div>
      </div>
      {source && <div className="grid items-start gap-4 md:grid-cols-2"><Select density="form" searchable label="Компания из набора" value={companyKey} disabled={busy} onChange={event => void loadCompany(source, event.target.value, horizon)} options={source.companies.map(item => ({ value: item.key, label: `${item.key === "single" ? "" : `${item.key} · `}${item.name}` }))} /><div className="flex gap-2 pt-1 text-sm text-[color:var(--text-secondary)]"><FileSpreadsheet size={18} /><span>Найдено компаний: {source.companies.length}. В один расчёт входит одна компания.</span></div></div>}
      {data && <div className="space-y-4">
        <div className="flex flex-wrap gap-x-6 gap-y-2 rounded-md bg-[color:var(--surface-subtle)] p-3 text-sm"><span>Операций: <strong>{data.operations.length.toLocaleString("ru-RU")}</strong></span><span>{displayDate(data.from)} — {displayDate(data.to)}</span><span>Точных повторов исключено: {data.duplicates}</span></div>
        <div className="grid gap-4 md:grid-cols-2"><Select density="form" label="Режим проверки" value={mode} disabled={running} onChange={event => setMode(event.target.value as RunOptions["mode"])} options={[{ value: "holdout", label: "Проверить на отложенном периоде" }, { value: "forecast", label: "Построить прогноз после конца файла" }]} /><Select density="form" label="Горизонт, дней" value={String(horizon)} disabled={running} onChange={event => { const days = Number(event.target.value); setHorizon(days); if (data) setCutoff(dayOffset(data.to, -days)); }} options={[7, 14, 30].map(value => ({ value: String(value), label: String(value) }))} />
          {mode === "holdout" && <Input label="Последний день истории для модели" type="date" value={cutoff} min={data.from} max={dayOffset(data.to, -horizon)} disabled={running} onChange={event => setCutoff(event.target.value)} />}
          <Input label="Резерв для проверки нехватки, ₽" type="number" min="0" max="10000000000000" step="0.01" value={reserve} disabled={running} onChange={event => setReserve(event.target.value)} /></div>
        <p className="text-sm text-[color:var(--text-secondary)]">{mode === "holdout" ? "В импорт войдут только операции до даты отсечения. Более поздние строки используются только для сравнения; переобучение не запрашивается." : "В API уйдёт вся история выбранной компании. Будущий факт отсутствует — MAE, MSE и матрица ошибок для этого прогона будут недоступны."}</p>
        <p className="text-xs text-[color:var(--text-secondary)]">Для каждого запуска создаётся отдельная контрольная компания. История, планы и настройки текущей компании сохраняются.</p>
        <Button disabled={busy || !cutoff} loading={running} onClick={() => void run()}>Запустить проверку</Button>
      </div>}
      {busy && <div role="status" className="flex items-center gap-2 text-sm"><LoaderCircle size={17} className="animate-spin" />{reading ? "Читаем выписку выбранной компании…" : stage}</div>}
      {error && <div role="alert" className="space-y-2 rounded-md border border-[color:var(--danger)] p-3 text-sm"><p>{error}</p>{created && <Button variant="outline" size="sm" onClick={() => void openCompany(created.id, "/sources")}>Открыть контрольную компанию</Button>}</div>}
    </SectionCard>
    {reports.length > 0 && !running && <SectionCard className="space-y-3 p-5"><ContentHeading level={2}>Последние проверки</ContentHeading><div className="flex flex-wrap gap-2">{reports.map(saved => <Button key={saved.id} variant={report?.id === saved.id ? "default" : "outline"} size="sm" onClick={() => { setReport(saved); setLogs(saved.logs); setError(null); }}>{saved.dataset_company} · {new Date(saved.created_at).toLocaleString("ru-RU")}</Button>)}</div><p className="text-xs text-[color:var(--text-secondary)]">Три последних отчёта этой рабочей компании сохраняются на сервере. Входные CSV включаются в ZIP только сразу после текущего расчёта.</p></SectionCard>}
    {report && <CheckpointResult report={report} download={() => downloadCheckpoint(report, reportInputs)} openForecast={() => void openCompany(report.company_id, "/forecast")} />}
    {(logs.length > 0 || report) && <ObservationLog logs={logs.length ? logs : report!.logs} />}
    {!source && !report && !running && <SectionCard className="space-y-3 p-5"><ContentHeading level={2}>Что будет в результате</ContentHeading><div className="grid gap-4 text-sm sm:grid-cols-3">{[["Прогноз", "Остаток по дням, диапазон p10–p90, даты и суммы возможной нехватки."], ["Проверка", "MAE, MSE, RMSE, WAPE и матрица ошибок по подтверждённому отложенному факту."], ["Материалы", "Протокол с SHA-256, реальные наблюдения API, расчёт метрик и CSV прогноза в одном ZIP."]].map(([title, description]) => <div key={title}><p className="font-medium">{title}</p><p className="mt-1 text-[color:var(--text-secondary)]">{description}</p></div>)}</div></SectionCard>}
  </div>;
}

function CheckpointResult({ report, download, openForecast }: { report: CheckpointReport; download: () => void; openForecast: () => void }) {
  const { forecast, metrics } = report;
  const days = [...forecast.history.slice(-14).map(point => ({ date: point.date, actual: point.balance })), ...metrics.points.map(point => ({ date: point.date, actual: point.actual, baseline: point.predicted, lowerBound: point.lower, upperBound: point.upper }))];
  const items = [["MAE, ₽", decimal(metrics.mae)], ["MSE, ₽²", decimal(metrics.mse)], ["RMSE, ₽", decimal(metrics.rmse)], ["WAPE остатка", fraction(metrics.wape)], ["Факт в p10–p90", fraction(metrics.coverage)], ["Дней для сравнения", `${metrics.samples} / ${report.horizon}`]];
  return <>
    <SectionCard className="space-y-4 p-5"><div className="flex flex-wrap items-start justify-between gap-4"><div><ContentHeading level={2}>Результат расчёта</ContentHeading><p className="mt-1 text-sm text-[color:var(--text-secondary)]">{report.company_name} · история по {displayDate(report.cutoff)} · прогноз до {displayDate(forecast.points.at(-1)!.date)}</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={openForecast}>Открыть контрольную компанию</Button><Button onClick={download}><Download size={16} className="mr-2" />Скачать результаты ZIP</Button></div></div>
      <div className={`rounded-md border p-3 text-sm ${forecast.fallback_used || forecast.low_confidence ? "border-[color:var(--warning)]" : "border-[color:var(--border)]"}`}><p>Модель: <strong>{forecast.model_used}</strong> · {forecast.fallback_used ? "упрощённый расчёт" : "ответ ML-сервиса"}{forecast.low_confidence ? " · ограниченная надёжность" : ""}</p><p className="mt-1 break-all text-xs text-[color:var(--text-secondary)]">Версия: {forecast.model_version || "не опубликована"}</p></div>
      {report.persistence_warning && <p role="alert" className="text-sm text-[color:var(--warning)]">{report.persistence_warning}</p>}
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-[color:var(--text-secondary)]" aria-label="Обозначения графика"><span className="flex items-center gap-2"><i className="inline-block h-0.5 w-5 bg-[color:var(--accent)]" />Прогноз p50</span><span className="flex items-center gap-2"><i className="inline-block h-0.5 w-5 bg-[color:var(--chart-series-primary)]" />Подтверждённый факт</span><span className="flex items-center gap-2"><i className="inline-block w-5 border-t border-dashed border-[color:var(--text-muted)]" />Границы p10–p90</span></div>
      <CashflowForecastChart days={days} height={350} showBounds showScenario={false} compactDates animate={false} />
      <p className="text-xs text-[color:var(--text-secondary)]">Линия факта после даты отсечения взята из отложенного периода; модель её не получала. Пропуски оставлены разрывами. Этот прогон проверяет загруженный набор, а не доступные деньги на сегодня.</p>
      {forecast.gaps.length > 0 && <div className="space-y-2">{forecast.gaps.map(gap => <div key={gap.id} className="flex flex-wrap justify-between gap-2 rounded-md bg-[color:var(--surface-subtle)] p-3 text-sm"><span>Возможная нехватка с {displayDate(gap.date)}</span><span>{gapAmount(gap).amount === null ? "Сумма не определена" : rubles(gapAmount(gap).amount!)} · {riskProbabilityText(gap, forecast)}</span></div>)}</div>}
      {forecast.gaps.length === 0 && <p className="text-sm">На выбранном горизонте модель не выделила кассовый разрыв.</p>}
    </SectionCard>
    <SectionCard className="space-y-4 p-5"><ContentHeading level={2}>Метрики прогноза остатка</ContentHeading><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{items.map(([label, value]) => <div key={label} className="rounded-md border border-[color:var(--border)] p-4"><p className="text-xs text-[color:var(--text-secondary)]">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums">{value}</p></div>)}</div>
      <p className="text-sm text-[color:var(--text-secondary)]">{report.mode === "forecast" ? "Будущий факт не предоставлен. Оценки ошибки и матрица ошибок недоступны." : metrics.samples ? `Сравнение по ${metrics.samples} подтверждённым дням. Исключено неизвестных или несверенных дней: ${metrics.excluded}. Это одна компания и одна дата старта, а не оценка качества на всей популяции.` : "В отложенном периоде нет подтверждённых дней для сравнения. Проверьте остатки и полноту выписки."}</p>
      <details className="text-xs text-[color:var(--text-secondary)]"><summary className="cursor-pointer">Формулы и область оценки</summary><p className="mt-2">MAE — среднее |p50 − факт|. MSE — среднее (p50 − факт)². RMSE — корень из MSE. WAPE — сумма абсолютных ошибок, делённая на сумму абсолютных фактических остатков. Покрытие — доля факта внутри p10–p90. При нулевом знаменателе метрика отсутствует. Ни одна метрика не подставляется из опубликованных оценок модели.</p></details>
    </SectionCard>
    <SectionCard className="space-y-4 p-5"><ContentHeading level={2}>Остаток ниже резерва: проверка по дням</ContentHeading><p className="text-sm text-[color:var(--text-secondary)]">Предсказание: p50 ниже резерва {rubles(report.reserve)}. Факт: подтверждённый остаток ниже того же резерва. Accuracy здесь относится к этому признаку, а не к категоризации операций или точности суммы. Фактический остаток включает финансирование собственником; скрытая потребность в таком финансировании отдельно не размечена.</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{[["Accuracy", metrics.accuracy], ["Precision", metrics.precision], ["Recall", metrics.recall], ["F1", metrics.f1]].map(([label, value]) => <div key={String(label)} className="rounded-md border border-[color:var(--border)] p-3"><p className="text-xs text-[color:var(--text-secondary)]">{label}</p><p className="mt-1 text-lg font-semibold tabular-nums">{fraction(value as number | null)}</p></div>)}</div>
      {metrics.confusion ? <Table aria-label="Матрица ошибок кассового разрыва"><TableHeader><TableRow><TableHead>Предсказание / факт</TableHead><TableHead numeric>Факт: нехватка</TableHead><TableHead numeric>Факт: нехватки нет</TableHead></TableRow></TableHeader><TableBody><TableRow><TableCell>Предсказана нехватка</TableCell><TableCell numeric>TP · {metrics.confusion.tp}</TableCell><TableCell numeric>FP · {metrics.confusion.fp}</TableCell></TableRow><TableRow><TableCell>Предсказано отсутствие нехватки</TableCell><TableCell numeric>FN · {metrics.confusion.fn}</TableCell><TableCell numeric>TN · {metrics.confusion.tn}</TableCell></TableRow></TableBody></Table> : <p className="text-sm text-[color:var(--text-secondary)]">Матрица ошибок недоступна без сопоставимого факта.</p>}
      <p className="text-xs text-[color:var(--text-secondary)]">Precision и Recall могут отсутствовать, если в выборке нет предсказанных или фактических положительных дней. Brier и калибровка вероятности недоступны: API не публикует полную дневную вероятность; она не восстанавливается из квантилей.</p>
    </SectionCard>
    <SectionCard className="space-y-3 p-5"><ContentHeading level={2}>Категоризация операций</ContentHeading><p className="text-sm">Проверено сохранённых операций: {report.classification.total.toLocaleString("ru-RU")}.</p><div className="flex flex-wrap gap-3 text-sm">{Object.entries(report.classification.by_method).map(([method, count]) => <span key={method}>{methodName[method] ?? method}: <strong>{count}</strong></span>)}</div><p className="text-sm text-[color:var(--text-secondary)]">Accuracy, Precision, Recall, F1 и матрица ошибок категоризации — недоступны. {report.classification.reason}</p></SectionCard>
    <SectionCard className="space-y-3 p-5"><ContentHeading level={2}>Протокол проверки</ContentHeading><div className="grid gap-2 text-sm sm:grid-cols-2"><p>Компания набора: {report.dataset_company}</p><p>Горизонт: {report.horizon} дней</p><p>Отправлено в API: {report.input.training_rows} операций</p><p>Не отправлено в API: {report.input.withheld_rows} операций</p></div><dl className="space-y-2 text-xs"><dt className="text-[color:var(--text-secondary)]">SHA-256 исходного файла</dt><dd className="break-all font-mono">{report.input.file_sha256}</dd><dt className="text-[color:var(--text-secondary)]">SHA-256 отправленной истории</dt><dd className="break-all font-mono">{report.input.training_sha256}</dd></dl><p className="text-xs text-[color:var(--text-secondary)]">Резерв, период, хеши файлов, версия модели, факт использования упрощённого расчёта и формулы включены в ZIP. Проверка не отправляет запросы на обучение или переобучение моделей.</p></SectionCard>
  </>;
}

function ObservationLog({ logs }: { logs: CheckpointLog[] }) {
  return <SectionCard className="space-y-4 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><ContentHeading level={2}>Лог выполнения проверки</ContentHeading><Button variant="outline" size="sm" onClick={() => downloadObservations(logs)}>Скачать логи JSONL</Button></div><p className="text-xs text-[color:var(--text-secondary)]">Реальная подготовка файла в браузере и подтверждённые ответы API. Эти записи не выдают себя за внутренние стадии M6; сквозной идентификатор серверных ML-логов пока отсутствует.</p><ol className="space-y-3">{logs.map((entry, index) => <li key={`${entry.at}:${index}`} className="flex items-start gap-3 border-t border-[color:var(--border)] pt-3">{entry.event === "run_failed" ? <AlertCircle size={17} className="mt-0.5 shrink-0 text-[color:var(--danger)]" /> : <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-[color:var(--accent)]" />}<div className="min-w-0 flex-1"><div className="flex flex-wrap justify-between gap-2 text-xs text-[color:var(--text-secondary)]"><span>{entry.at.slice(11, 23)} UTC</span><span>+{decimal((entry.elapsed_ms ?? 0) / 1000, 1)} с</span></div><p className="mt-1 text-sm">{entry.message}</p>{entry.details && <details className="mt-1 text-xs text-[color:var(--text-secondary)]"><summary className="cursor-pointer">Данные шага</summary><pre className="mt-2 overflow-x-auto rounded-md bg-[color:var(--surface-subtle)] p-3">{JSON.stringify(entry.details, null, 2)}</pre></details>}</div></li>)}</ol></SectionCard>;
}
