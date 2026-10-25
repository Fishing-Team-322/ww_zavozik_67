import { strToU8, zipSync } from "fflate";
import type { CheckpointReport } from "./types";

export function checkpointArchive(report: CheckpointReport, inputs?: { trainingCSV: string; withheldCSV: string }): Uint8Array {
  const json = (value: unknown) => strToU8(JSON.stringify(value, null, 2));
  const protocol = { version: report.version, id: report.id, declared_at: report.logs.find(log => log.event === "protocol_frozen")?.at,
    mode: report.mode, company: report.dataset_company, cutoff: report.cutoff, horizon: report.horizon, reserve: report.reserve,
    input: report.input, model: report.forecast.model_used, model_version: report.forecast.model_version, fallback_used: report.forecast.fallback_used,
    future_rows_excluded_from_upload: report.mode === "holdout", fitting_or_retraining_requested: false,
    risk_decision: "predicted p50 < reserve; actual reconciled balance < reserve", log_scope: "observed browser preparation and actual HTTP/API results; not M6 internal stages" };
  const forecastCSV = "date,p10,p50,p90,actual_balance,actual_observed\n" + report.metrics.points.map(point => [point.date, point.lower, point.predicted, point.upper, point.actual ?? "", point.observed].join(",")).join("\n") + "\n";
  const files: Record<string, Uint8Array> = { "protocol.json": json(protocol), "report.json": json(report), "forecast.json": json(report.forecast), "metrics.json": json(report.metrics),
    "forecast.csv": strToU8(forecastCSV), "observations.jsonl": strToU8(report.logs.map(log => JSON.stringify(log)).join("\n") + "\n"),
    "README.txt": strToU8(`Проверка контрольного датасета\n\nПрогноз получен от API. Метрики и сверка факта рассчитаны в браузере по сохранённому ответу.\nВ режиме holdout будущие строки исключены из загруженной истории до вызова прогноза.\nMAE = mean(abs(p50-actual)); MSE = mean((p50-actual)^2); RMSE = sqrt(MSE).\nWAPE = sum(abs(p50-actual))/sum(abs(actual)); coverage = доля факта внутри p10–p90.\nМатрица ошибок относится к дням с балансом ниже резерва, решение прогноза — p50 < reserve.\nAccuracy=(TP+TN)/N; precision=TP/(TP+FP); recall=TP/(TP+FN); F1=2TP/(2TP+FP+FN).\nПри нулевом знаменателе оценка отсутствует. Неизвестный факт не заменён нулём.\nНет независимых эталонных категорий — нет Accuracy/precision/recall/F1 категоризации.\nВероятность отдельного разрыва не является Accuracy. Дневные вероятности и Brier не восстанавливаются из квантилей.\nЛог фиксирует реально выполненные действия клиента и ответы API. Это не внутренние стадии M6.\n${inputs ? "history.csv — точный CSV, отправленный в API. withheld.csv — не отправленные модели строки." : "В этом архиве нет CSV входных строк: страница восстановлена из сохранённого отчёта. Используйте исходный файл и экспорт контрольной компании."}\n`) };
  if (inputs) { files["history.csv"] = strToU8(inputs.trainingCSV); files["withheld.csv"] = strToU8(inputs.withheldCSV); }
  return zipSync(files, { level: 6 });
}

export function downloadCheckpoint(report: CheckpointReport, inputs?: { trainingCSV: string; withheldCSV: string }) {
  const bytes = checkpointArchive(report, inputs);
  const url = URL.createObjectURL(new Blob([Uint8Array.from(bytes).buffer], { type: "application/zip" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `checkpoint-${report.dataset_company.replace(/[^\p{L}\p{N}_-]/gu, "_").slice(0, 60)}-${report.id.slice(0, 8)}.zip`; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function downloadObservations(logs: CheckpointReport["logs"]) {
  const url = URL.createObjectURL(new Blob([logs.map(log => JSON.stringify(log)).join("\n") + "\n"], { type: "application/x-ndjson" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = "checkpoint-observations.jsonl"; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
