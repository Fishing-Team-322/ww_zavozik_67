import test from "node:test";
import assert from "node:assert/strict";
import { strFromU8, strToU8, unzipSync, zipSync } from "fflate";
import { ApiClient, ApiError, type Forecast } from "../src/shared/api/client";
import { csvRecords, inspectDataset, readControlCompany, operationsCSV } from "../src/features/checkpoint/model/dataset";
import { actualBalances, evaluateForecast } from "../src/features/checkpoint/model/metrics";
import { runCheckpoint, saveCheckpointReport, splitControlData } from "../src/features/checkpoint/model/runner";
import { checkpointArchive } from "../src/features/checkpoint/model/export";
import type { CheckpointReport, ControlData, ControlOperation } from "../src/features/checkpoint/model/types";

const op = (id: string, date: string, amount: number, balance: number | null, direction: "in" | "out" = "in"): ControlOperation => ({ id, company: "C001", date, amount, balance, direction, counterparty: "Клиент", inn: "0012345678", purpose: "Оплата" });
const fixture = () => Array.from({ length: 21 }, (_, index) => op(`row-${index + 1}`, `2026-01-${String(index + 1).padStart(2, "0")}`, 10, 100 + index * 10));
const dataOf = (operations: ControlOperation[]): ControlData => ({ company: { key: "C001", name: "Компания", legalForm: "ООО", industry: "services" }, operations, duplicates: 0, from: operations[0].date, to: operations.at(-1)!.date });
function prediction(values: number[], asOf = "2026-01-14"): Forecast {
  return { as_of: asOf, horizon: values.length, model_used: "test_model", flow_scope: "business_without_internal_transfers", model_version: "v1", fallback_used: false, low_confidence: false, warnings: [], history: [], gaps: [], markers: [], opening_balance: 230, safe_to_spend: 0, status: "warning", headline: "test", points: values.map((value, index) => ({ date: `2026-01-${String(15 + index).padStart(2, "0")}`, p10: value - 5, p50: value, p90: value + 5, is_workday: true })) } as Forecast;
}

test("checkpoint CSV preserves quoted newlines, Cyrillic and leading zero INNs", async () => {
  const first = op("one", "2026-01-01", 10.25, 90);
  first.purpose = 'Оплата; по "договору"\nВторая строка';
  const csv = "\uFEFF" + operationsCSV([first, op("two", "2026-01-02", 10, 100)]);
  const source = await inspectDataset(new File([csv], "statement.csv"));
  assert.equal(source.companies.length, 1);
  const selected = await readControlCompany(source, "single");
  assert.equal(selected.operations[0].purpose, first.purpose);
  assert.equal(selected.operations[0].inn, "0012345678");
  assert.equal(selected.operations[0].amount, 10.25);
  const rows: string[][] = [];
  for await (const row of csvRecords(new Blob(["a,b\r\n\"x\"\"y\",\"z\nq\"\r\n"]))) rows.push(row);
  assert.deepEqual(rows, [["a", "b"], ['x"y', "z\nq"]]);
});

test("combined CSV is separated by company and conflicting operation IDs stop a run", async () => {
  const header = "company_id;operation_id;operation_date;amount;direction;balance_eod\n";
  const source = await inspectDataset(new File([header + "C001;x;2026-01-01;10;Поступление;100\nC002;x;2026-01-02;20;Списание;200\nC001;x;2026-01-01;10;Поступление;100\n"], "all_operations.csv"));
  const selected = await readControlCompany(source, "C001");
  assert.equal(source.companies.length, 2); assert.equal(selected.duplicates, 1); assert.equal(selected.operations.length, 1);
  const conflicting = await inspectDataset(new File([header + "C001;x;2026-01-01;10;in;100\nC001;x;2026-01-01;20;in;100\n"], "bad.csv"));
  await assert.rejects(readControlCompany(conflicting, "C001"), /одинаковый operation_id/);
});

test("CSV validation rejects broken amounts, invalid dates and non-CSV inputs", async () => {
  await assert.rejects(inspectDataset(new File(["date;amount;direction;balance\n2026-02-30;10;in;100\n"], "bad.csv")), /дата/);
  await assert.rejects(inspectDataset(new File(["date;amount;direction;balance\n2026-01-01;NaN;in;100\n"], "bad.csv")), /сумма/);
  const bytes = zipSync({ "../evil.csv": strToU8("bad") });
  await assert.rejects(inspectDataset(new File([Uint8Array.from(bytes).buffer], "unsafe.zip")), /выберите CSV/);
});

test("empty company IDs cannot be reassigned to whichever explicit company is selected", async () => {
  const source = await inspectDataset(new File(["company_id;operation_id;operation_date;amount;direction;balance_eod\nC001;a;2026-01-01;10;in;100\nC002;b;2026-01-02;20;out;200\n;unassigned;2026-01-03;30;in;300\n"], "mixed.csv"));
  assert.deepEqual(source.companies.map(company => company.key).sort(), ["C001", "C002", "single"]);
  for (const [key, id] of [["C001", "a"], ["C002", "b"], ["single", "unassigned"]]) {
    const selected = await readControlCompany(source, key);
    assert.deepEqual(selected.operations.map(op => op.id), [id]);
  }
});

test("reconciliation excludes unknown intervals instead of fabricating zero balances", () => {
  const rows = [op("a", "2026-01-01", 100, 100), op("b", "2026-01-04", 10, 500), op("c", "2026-01-06", 10, 510)];
  const days = actualBalances(rows);
  assert.equal(days[0].balance, 100);
  assert.deepEqual(days.slice(1, 4).map(day => [day.balance, day.observed]), [[null, false], [null, false], [null, false]]);
  assert.equal(days[4].balance, 500); assert.equal(days[5].balance, 510);
  const conflict = actualBalances([op("a", "2026-01-01", 10, 100), op("b", "2026-01-01", 20, 101)]);
  assert.equal(conflict[0].observed, false); assert.equal(conflict[0].balance, null);
});

test("holdout metrics distinguish amount error from the daily risk confusion matrix", () => {
  const forecast = prediction([-10, -10, 10, 10]);
  const truth = [-20, 20, -10, 10].map((balance, index) => ({ date: forecast.points[index].date, balance, observed: true }));
  const metrics = evaluateForecast(forecast, truth, 0, true);
  assert.equal(metrics.mae, 15); assert.equal(metrics.mse, 350); assert.equal(metrics.rmse, Math.sqrt(350)); assert.equal(metrics.wape, 1);
  assert.equal(metrics.coverage, .25); assert.equal(metrics.accuracy, .5); assert.equal(metrics.precision, .5); assert.equal(metrics.recall, .5); assert.equal(metrics.f1, .5);
  assert.deepEqual(metrics.confusion, { tp: 1, fp: 1, fn: 1, tn: 1 });
});

test("missing truth and zero denominators remain unavailable, never good-looking zero errors", () => {
  const forecast = prediction([0, 0]);
  const truth = forecast.points.map(point => ({ date: point.date, balance: 0, observed: true }));
  const available = evaluateForecast(forecast, truth, 0, true);
  assert.equal(available.mae, 0); assert.equal(available.wape, null); assert.equal(available.precision, null); assert.equal(available.recall, null); assert.equal(available.f1, null);
  const absent = evaluateForecast(forecast, truth, 0, false);
  assert.equal(absent.samples, 0); assert.equal(absent.mae, null); assert.equal(absent.confusion, null);
  const partial = evaluateForecast(forecast, [{ ...truth[0], observed: false, balance: null }, truth[1]], 0, true);
  assert.equal(partial.samples, 1); assert.equal(partial.excluded, 1); assert.equal(partial.points[0].actual, null);
});

test("cutoff uses only past operations, fixes the actual last bank day and rejects insufficient holdout", () => {
  const data = dataOf(fixture());
  const result = splitControlData(data, { mode: "holdout", horizon: 7, cutoff: "2026-01-14", reserve: 0 });
  assert.equal(result.training.length, 14); assert.equal(result.withheld.length, 7); assert.equal(result.asOf, "2026-01-14");
  assert.equal(result.trainingCSV.includes("2026-01-15"), false); assert.equal(result.withheldCSV.includes("2026-01-21"), true);
  assert.throws(() => splitControlData(data, { mode: "holdout", horizon: 30, cutoff: "2026-01-14", reserve: 0 }), /недостаточно/);
});

test("API runner uploads only the declared history and exports exact input evidence", async () => {
  const data = dataOf(fixture()), source = await inspectDataset(new File([operationsCSV(data.operations)], "input.csv"));
  const forecast = prediction(Array.from({ length: 7 }, (_, index) => 240 + index * 10));
  const calls: string[] = []; let uploaded = "";
  const fake = { async request<T>(path: string, options?: Parameters<ApiClient["request"]>[1]): Promise<T> {
    calls.push(path);
    if (path === "/v1/companies") return { id: "test-company", name: "Контроль" } as T;
    if (path.endsWith("/uploads")) { uploaded = await (options!.form!.get("file") as Blob).text(); return { id: "job-id", status: "done", result_ref: "/v1/imports/11111111-1111-1111-1111-111111111111" } as T; }
    if (path.startsWith("/v1/imports/")) return { added: 14, duplicates: 0, errors: [] } as T;
    if (path.endsWith("/updates")) return { data_revision: 1, forecast_revision: 1, pending_jobs: 0 } as T;
    if (path.includes("/forecast?")) return forecast as T;
    if (path.includes("/operations?")) return { items: Array.from({ length: 14 }, () => ({ category_method: "rule" })), next_cursor: null, total: 14 } as T;
    throw new Error(path);
  } };
  const result = await runCheckpoint(fake, source, data, { mode: "holdout", horizon: 7, cutoff: "2026-01-14", reserve: 0 }, new AbortController().signal, { log() {}, stage() {}, created() {} });
  assert.equal(uploaded.includes("2026-01-15"), false); assert.equal(uploaded.includes("2026-01-14"), true);
  assert.equal(result.report.metrics.samples, 7); assert.equal(result.report.metrics.mae, 0);
  assert.equal(calls.some(path => /train|retrain/.test(path)), false);
  assert.equal(result.report.classification.total, 14);
  const archive = unzipSync(checkpointArchive(result.report, result));
  assert.equal(strFromU8(archive["history.csv"]), uploaded);
  assert.equal(strFromU8(archive["withheld.csv"]).includes("2026-01-21"), true);
  const protocol = JSON.parse(strFromU8(archive["protocol.json"]));
  assert.equal(protocol.future_rows_excluded_from_upload, true);
  assert.equal(protocol.fitting_or_retraining_requested, false);
});

test("report persistence merges concurrent workspace changes rather than overwriting them", async () => {
  let gets = 0, puts = 0;
  const fake = { async request<T>(path: string, options?: Parameters<ApiClient["request"]>[1]): Promise<T> {
    if (!options?.method) { gets++; return { version: gets, data: { existing: gets === 1 ? "before" : "concurrent edit" } } as T; }
    puts++;
    if (puts === 1) throw new ApiError(409, "version_conflict", "changed");
    const body = options.json as { expected_version: number; data: Record<string, unknown> };
    assert.equal(body.expected_version, 2); assert.equal(body.data.existing, "concurrent edit"); return {} as T;
  } };
  await saveCheckpointReport(fake, "workspace", { version: 1, id: "report" } as CheckpointReport, new AbortController().signal);
  assert.equal(puts, 2); assert.equal(gets, 2);
});
