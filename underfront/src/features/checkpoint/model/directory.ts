import { validInn } from "../../../shared/lib/inn";
import { csvRecords, operationRecords, sha256 } from "./dataset";
import type { ControlCompany, ControlSource, DirectoryAudit } from "./types";

const MAX_FILE = 80 * 1024 * 1024;
const MAX_TOTAL = 160 * 1024 * 1024;
const metadataFields = ["company_id", "company_name", "company_inn", "legal_form", "industry", "first_operation_date", "last_operation_date", "operations_count"] as const;
type Metadata = DirectoryAudit["metadata"][number];
const validDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

async function readMetadata(file: File): Promise<Metadata[]> {
  let header: string[] | undefined;
  const result: Metadata[] = [], ids = new Set<string>();
  for await (const row of csvRecords(file)) {
    if (!header) {
      header = row.map(value => value.trim().toLowerCase());
      for (const field of metadataFields) if (header.filter(value => value === field).length !== 1) throw new Error(`companies.csv: нужен один столбец ${field}.`);
      continue;
    }
    const values = Object.fromEntries(metadataFields.map(key => [key, (row[header!.indexOf(key)] ?? "").trim()]));
    const count = Number(values.operations_count);
    if (!values.company_id || ids.has(values.company_id)) throw new Error("companies.csv: пустой или повторный company_id.");
    if (!values.company_name || new TextEncoder().encode(values.company_name).byteLength > 300 || !values.industry || new TextEncoder().encode(values.industry).byteLength > 120 || !/^\d{10}(\d{2})?$/.test(values.company_inn) || !validInn(values.company_inn) || !["ООО", "ИП"].includes(values.legal_form)) throw new Error(`companies.csv: некорректные реквизиты ${values.company_id}.`);
    if (!validDate(values.first_operation_date) || !validDate(values.last_operation_date) || values.first_operation_date > values.last_operation_date || !/^\d+$/.test(values.operations_count) || !Number.isSafeInteger(count) || count < 1) throw new Error(`companies.csv: некорректные период или operations_count ${values.company_id}.`);
    ids.add(values.company_id);
    result.push({ ...values, operations_count: count } as Metadata);
    if (result.length > 500) throw new Error("В одном наборе допускается до 500 компаний.");
  }
  if (!result.length) throw new Error("companies.csv не содержит компаний.");
  return result;
}

/** Treat paths and README as data only. The combined file is authoritative; mirrors never add operations. */
export async function inspectDirectory(files: File[], progress?: (rows: number) => void): Promise<ControlSource> {
  if (!files.length || files.length > 1000) throw new Error("Выберите папку набора: от 1 до 1000 файлов.");
  const paths = new Map<string, { file: File; fullPath: string }>(), seenPaths = new Set<string>();
  let root = "", bytes = 0;
  for (const file of files) {
    const fullPath = file.webkitRelativePath;
    const segments = fullPath.split("/");
    if (segments.length < 2 || segments.some(part => !part || part === "." || part === ".." || /[\\\x00-\x1f]/.test(part)) || file.name !== segments.at(-1)) throw new Error("Не удалось безопасно прочитать относительные пути. Выберите папку через кнопку.");
    if (!root) root = segments[0];
    if (root !== segments[0]) throw new Error("Выберите одну корневую папку набора.");
    const path = segments.slice(1).join("/"), key = path.toLowerCase();
    if (seenPaths.has(key)) throw new Error(`В папке повторяется путь ${path}.`);
    if (file.size > MAX_FILE || (bytes += file.size) > MAX_TOTAL) throw new Error("Лимит папки — 160 МиБ, одного файла — 80 МиБ.");
    paths.set(path, { file, fullPath }); seenPaths.add(key);
  }
  const canonical = paths.get("all_operations.csv"), metadataFile = paths.get("companies.csv");
  if (!canonical || !metadataFile) throw new Error("В корне папки нужны all_operations.csv и companies.csv. Отдельную выписку можно выбрать как CSV.");
  const metadata = await readMetadata(metadataFile.file);
  const groups = new Map<string, { signatures: Map<string, string>; from: string; to: string }>();
  let rows = 0;
  for await (const op of operationRecords(canonical.file)) {
    let group = groups.get(op.company);
    if (!group) { group = { signatures: new Map(), from: op.date, to: op.date }; groups.set(op.company, group); }
    const signature = JSON.stringify(op), previous = group.signatures.get(op.id);
    if (previous !== undefined && previous !== signature) throw new Error(`all_operations.csv: конфликт operation_id ${op.id}.`);
    group.signatures.set(op.id, signature); group.from = group.from < op.date ? group.from : op.date; group.to = group.to > op.date ? group.to : op.date;
    if (groups.size > 500) throw new Error("В одном наборе допускается до 500 компаний.");
    if (++rows % 5000 === 0) progress?.(rows);
  }
  progress?.(rows);
  if (!groups.size || groups.size !== metadata.length || metadata.some(item => !groups.has(item.company_id))) throw new Error("company_id в companies.csv не совпадают с компаниями all_operations.csv.");
  const companies: ControlCompany[] = metadata.map(item => {
    const group = groups.get(item.company_id)!;
    if (item.operations_count !== group.signatures.size || item.first_operation_date !== group.from || item.last_operation_date !== group.to) throw new Error(`companies.csv: operations_count или период ${item.company_id} не совпадают с уникальными операциями.`);
    return { key: item.company_id, name: item.company_name, inn: item.company_inn, legalForm: item.legal_form, industry: item.industry, rows: group.signatures.size, from: group.from, to: group.to };
  }).sort((a, b) => a.key.localeCompare(b.key));
  const mirrors: DirectoryAudit["mirrors"] = [];
  for (const [path, entry] of paths) {
    if (!path.startsWith("statements/") || !path.toLowerCase().endsWith(".csv")) continue;
    const key = path.slice("statements/".length, -4), group = groups.get(key);
    if (key.includes("/") || !group) throw new Error(`Зеркальная выписка ${path}: company_id отсутствует в основном файле.`);
    const ids = new Set<string>(); let duplicates = 0;
    for await (const op of operationRecords(entry.file)) {
      if (op.company !== key || group.signatures.get(op.id) !== JSON.stringify(op)) throw new Error(`Зеркальная выписка ${path} не совпадает с all_operations.csv: operation_id ${op.id}.`);
      if (ids.has(op.id)) duplicates++; ids.add(op.id);
    }
    if (ids.size !== group.signatures.size) throw new Error(`Зеркальная выписка ${path}: неполный набор operation_id.`);
    mirrors.push({ relative_path: entry.fullPath, company: key, unique_operations: ids.size, duplicates, excluded_from_import: true });
  }
  const manifest: DirectoryAudit["manifest"] = [];
  for (const [path, entry] of [...paths].sort(([a], [b]) => a.localeCompare(b))) {
    const role = path === "all_operations.csv" ? "canonical" : path === "companies.csv" ? "metadata" : mirrors.some(mirror => mirror.relative_path === entry.fullPath) ? "mirror" : path === "README.md" ? "documentation" : "unused";
    manifest.push({ relative_path: entry.fullPath, bytes: entry.file.size, sha256: await sha256(entry.file), role });
  }
  return { file: canonical.file, kind: "directory", companies, directory: { name: root, canonical_source: canonical.fullPath, metadata_source: metadataFile.fullPath, manifest, mirrors, metadata, raw_files_modified: false, raw_files_uploaded: false } };
}
