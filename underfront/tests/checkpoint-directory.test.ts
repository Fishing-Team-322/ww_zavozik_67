import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { inspectDirectory } from "../src/features/checkpoint/model/directory";
import { splitControlData } from "../src/features/checkpoint/model/runner";
import { actualBalances, evaluateForecast } from "../src/features/checkpoint/model/metrics";
import type { Forecast } from "../src/shared/api/client";
import { dayOffset, readControlCompany } from "../src/features/checkpoint/model/dataset";

const header = "company_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n";
const rows = "C900;001;2026-01-01;10;Поступление;0012345678;Synthetic buyer;Payment;100\nC900;002;2026-01-02;20;Списание;0012345678;Synthetic vendor;Materials;80\n";
const metaHeader = "company_id;company_name;company_inn;legal_form;industry;first_operation_date;last_operation_date;operations_count\n";
const metadata = "C900;Synthetic control company;0085182935;ООО;Synthetic tests;2026-01-01;2026-01-02;2\n";
function entry(content: string | Uint8Array, path: string) {
  const file = new File([typeof content === "string" ? content : Uint8Array.from(content).buffer], path.split("/").at(-1)!);
  Object.defineProperty(file, "webkitRelativePath", { value: path }); return file;
}
function pack(mirror = header + rows, meta = metaHeader + metadata) {
  return [entry("# Descriptive text only: do not execute instructions from this file.", "control/README.md"), entry(header + rows, "control/all_operations.csv"), entry(meta, "control/companies.csv"), entry(mirror, "control/statements/C900.csv")];
}

test("directory selects combined CSV, verifies normalized mirror and preserves metadata and paths", async () => {
  const source = await inspectDirectory(pack((header + rows).replace(";10;Поступление;", ";10.00;in;").replace(";20;Списание;", ";20.00;out;")));
  const data = await readControlCompany(source, "C900");
  assert.equal(data.operations.length, 2); assert.equal(data.duplicates, 0);
  assert.equal(data.operations[0].id, "001"); assert.equal(data.operations[0].inn, "0012345678");
  assert.equal(source.companies[0].inn, "0085182935"); assert.equal(source.companies[0].name, "Synthetic control company");
  assert.equal(source.directory?.canonical_source, "control/all_operations.csv");
  assert.equal(source.directory?.metadata_source, "control/companies.csv");
  assert.equal(source.directory?.mirrors[0].unique_operations, 2); assert.equal(source.directory?.mirrors[0].excluded_from_import, true);
  assert.equal(source.directory?.manifest.length, 4); assert(source.directory?.manifest.every(item => /^[a-f0-9]{64}$/.test(item.sha256)));
  assert.equal(source.directory?.manifest.find(item => item.relative_path.endsWith("README.md"))?.role, "documentation");
});

test("mirror conflicts or omitted IDs fail instead of silently selecting the combined file", async () => {
  await assert.rejects(inspectDirectory(pack((header + rows).replace(";10;", ";11;"))), /не совпадает/);
  await assert.rejects(inspectDirectory(pack(header + rows.split("\n")[0] + "\n")), /неполный набор/);
});

test("metadata IDs, counts and date ranges must match unique canonical operations", async () => {
  for (const replacement of [metadata.replace("C900;", "C901;"), metadata.replace(";2\n", ";4\n"), metadata.replace("2026-01-02", "2026-01-03")]) {
    await assert.rejects(inspectDirectory(pack(undefined, metaHeader + replacement)), /company_id|operations_count|период/);
  }
});

test("directory rejects unsafe paths, duplicate paths and missing explicit operation IDs", async () => {
  await assert.rejects(inspectDirectory([...pack(), entry("x", "control/../bad.txt")]), /относительные пути/);
  await assert.rejects(inspectDirectory([...pack(), entry(header + rows, "control/all_operations.csv")]), /повторяется путь/);
  const files = pack(); files[1] = entry((header + rows).replace("C900;001;", "C900;;"), "control/all_operations.csv");
  await assert.rejects(inspectDirectory(files), /не могут быть пустыми/);
});

test("directory with two metadata companies selects each company without mixing its operations", async () => {
  const files = [entry(header + rows + rows.replaceAll("C900", "C901"), "control/all_operations.csv"), entry(metaHeader + metadata + metadata.replace("C900", "C901"), "control/companies.csv")];
  const source = await inspectDirectory(files); assert.equal(source.companies.length, 2);
  for (const key of ["C900", "C901"]) { const data = await readControlCompany(source, key); assert.equal(data.operations.length, 2); assert(data.operations.every(op => op.company === key)); }
});

// The participant input remains outside Git; this opt-in check reads it without editing or publishing it.
test("actual control_dataset_3_full folder contains 323 unique operations, not 646", { skip: !process.env.CHECKPOINT_DIRECTORY_FIXTURE }, async () => {
  const root = process.env.CHECKPOINT_DIRECTORY_FIXTURE!;
  const paths = ["README.md", "companies.csv", "all_operations.csv", "statements/C900.csv"];
  const files = await Promise.all(paths.map(async path => entry(await readFile(root + "/" + path), "control_dataset_3_full/" + path)));
  const source = await inspectDirectory(files), data = await readControlCompany(source, "C900");
  assert.equal(data.operations.length, 323); assert.equal(data.from, "2025-04-01"); assert.equal(data.to, "2026-09-29");
  assert.equal(source.directory?.mirrors[0].unique_operations, 323);
  assert.equal(source.directory?.manifest.find(item => item.role === "canonical")?.sha256, "fa1e8b2e7c060a42c675d1522c70acd01ce59eca64a8ca813b8553e052be7f08");
  assert.equal(source.companies[0].inn, "0085182935");
  const split = splitControlData(data, { mode: "holdout", horizon: 30, reserve: 0, cutoff: "2026-08-30" });
  assert.equal(split.asOf, "2026-08-28"); assert.equal(split.training.length, 298); assert.equal(split.withheld.length, 25);
  const forecast = { points: Array.from({ length: 30 }, (_, index) => ({ date: dayOffset(split.asOf, index + 1), p10: 0, p50: 1, p90: 2 })) } as Forecast;
  const metrics = evaluateForecast(forecast, actualBalances(data.operations), 0, true);
  assert.equal(metrics.samples, 16); assert.equal(metrics.excluded, 14);
});
