import type { ControlCompany, ControlData, ControlOperation, ControlSource } from "./types";

const MAX_CSV = 80 * 1024 * 1024;
const MAX_ROWS = 350_000;
const DAY = 86400000;
export const dayOffset = (date: string, days: number) => new Date(Date.parse(`${date}T00:00:00Z`) + days * DAY).toISOString().slice(0, 10);
const fieldNames: Record<string, string[]> = {
  date: ["operation_date", "date", "op_date", "дата"], amount: ["amount", "сумма"], direction: ["direction", "направление"],
  id: ["operation_id", "id"], company: ["company_id"], counterparty: ["counterparty_name", "counterparty", "контрагент"],
  inn: ["counterparty_inn", "inn", "инн"], purpose: ["payment_purpose", "purpose", "назначение"], balance: ["balance_eod", "balance", "остаток"],
};

/** Incremental RFC4180 reader: a combined CSV is scanned without retaining all companies' operations. */
export async function* csvRecords(blob: Blob): AsyncGenerator<string[]> {
  const reader = blob.stream().getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let separator = "", prefix = "", field = "", row: string[] = [], quoted = false, afterQuote = false, afterCR = false, count = 0;
  function* consume(text: string): Generator<string[]> {
    for (const char of text) {
      if (afterCR) { afterCR = false; if (char === "\n") continue; }
      if (quoted) {
        if (afterQuote) {
          if (char === '"') { field += '"'; afterQuote = false; continue; }
          quoted = false; afterQuote = false;
          if (char !== separator && char !== "\r" && char !== "\n") {
            if (char === " " || char === "\t") continue;
            throw new Error("После закрывающей кавычки должен быть разделитель CSV.");
          }
        } else if (char === '"') { afterQuote = true; continue; }
        else { field += char; if (field.length > 8192) throw new Error("Ячейка CSV превышает 8192 символа."); continue; }
      }
      if (char === '"' && field === "") quoted = true;
      else if (char === separator) { row.push(field); field = ""; if (row.length > 100) throw new Error("В CSV более 100 столбцов."); }
      else if (char === "\n" || char === "\r") {
        row.push(field); field = ""; afterCR = char === "\r";
        if (row.some(value => value !== "")) { if (++count > MAX_ROWS) throw new Error("В файле более 350 000 строк."); yield row; }
        row = [];
      } else { field += char; if (field.length > 8192) throw new Error("Ячейка CSV превышает 8192 символа."); }
    }
  }
  try {
    while (true) {
      const chunk = await reader.read();
      const text = decoder.decode(chunk.value, { stream: !chunk.done });
      if (!separator) {
        prefix += text;
        if (!prefix.includes("\n") && !chunk.done) { if (prefix.length > 32768) throw new Error("Не найден заголовок CSV."); continue; }
        prefix = prefix.replace(/^\uFEFF/, "");
        const header = prefix.split(/\r?\n/, 1)[0];
        separator = [";", ",", "\t"].sort((a, b) => header.split(b).length - header.split(a).length)[0];
        yield* consume(prefix); prefix = "";
      } else yield* consume(text);
      if (chunk.done) break;
    }
    if (quoted && !afterQuote) throw new Error("В CSV не закрыты кавычки.");
    if (field !== "" || row.length) { row.push(field); yield row; }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

function columns(header: string[]) {
  const normalized = header.map(value => value.trim().toLowerCase());
  const out: Record<string, number> = {};
  for (const [key, aliases] of Object.entries(fieldNames)) {
    const matches = normalized.flatMap((name, index) => aliases.includes(name) ? [index] : []);
    if (matches.length > 1) throw new Error(`Неоднозначный столбец: ${key}.`);
    out[key] = matches[0] ?? -1;
  }
  for (const key of ["date", "amount", "direction", "balance"]) if (out[key] < 0) throw new Error(`Нет столбца «${fieldNames[key][0]}». Нужны дата, сумма, направление и остаток.`);
  return out;
}
const get = (row: string[], index: number) => (row[index] ?? "").trim();
function numeric(raw: string, nullable = false): number | null {
  if (!raw && nullable) return null;
  const value = raw.replace(/[\s\u00a0]/g, "").replace(",", ".");
  if (!value || !/^-?\d+(?:\.\d{1,2})?$/.test(value) || !Number.isFinite(Number(value)) || Math.abs(Number(value)) > 1e13) throw new Error("Некорректная денежная сумма.");
  return Number(value);
}
function operation(row: string[], map: Record<string, number>, fallback: string, index: number): ControlOperation {
  const date = get(row, map.date), rawDirection = get(row, map.direction).toLowerCase();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date) throw new Error(`Строка ${index}: дата должна быть ГГГГ-ММ-ДД.`);
  const direction = ["in", "поступление", "приход"].includes(rawDirection) ? "in" : ["out", "списание", "расход"].includes(rawDirection) ? "out" : null;
  if (!direction) throw new Error(`Строка ${index}: неизвестное направление платежа.`);
  const amount = numeric(get(row, map.amount))!;
  if (amount <= 0) throw new Error(`Строка ${index}: сумма должна быть положительной.`);
  return { id: get(row, map.id) || `row-${index}`, company: get(row, map.company) || fallback, date, amount, direction,
    counterparty: get(row, map.counterparty), inn: get(row, map.inn), purpose: get(row, map.purpose), balance: numeric(get(row, map.balance), true) };
}
export async function inspectDataset(file: File, progress?: (rows: number) => void): Promise<ControlSource> {
  if (!file.size) throw new Error("Файл пуст.");
  if (!/\.csv$/i.test(file.name)) throw new Error("Для контрольного набора выберите CSV с исходными полями датасета.");
  if (file.size > MAX_CSV) throw new Error("CSV должен быть не больше 80 МиБ.");
  return { file, kind: "csv", companies: await inspectCSV(file, file.name, progress) };
}

async function inspectCSV(blob: Blob, filename: string, progress?: (rows: number) => void): Promise<ControlCompany[]> {
  let map: Record<string, number> | undefined, index = 0;
  const companies = new Map<string, ControlCompany>();
  for await (const row of csvRecords(blob)) {
    if (!map) { map = columns(row); continue; }
    const op = operation(row, map, "single", ++index);
    let company = companies.get(op.company);
    if (!company) { company = { key: op.company, name: op.company === "single" ? filename.replace(/\.csv$/i, "") : op.company, industry: "Контрольный набор", legalForm: "ООО", rows: 0, from: op.date, to: op.date }; companies.set(op.company, company); }
    company.rows!++; company.from = company.from! < op.date ? company.from : op.date; company.to = company.to! > op.date ? company.to : op.date;
    if (index % 5000 === 0) progress?.(index);
    if (companies.size > 500) throw new Error("В одном наборе допускается до 500 компаний.");
  }
  if (!index) throw new Error("В CSV нет операций.");
  progress?.(index);
  return [...companies.values()].sort((a, b) => a.key.localeCompare(b.key));
}

export async function readControlCompany(source: ControlSource, key: string): Promise<ControlData> {
  const company = source.companies.find(item => item.key === key);
  if (!company) throw new Error("Выберите компанию из набора.");
  const blob: Blob = source.file;
  const operations: ControlOperation[] = [], seen = new Map<string, string>();
  let map: Record<string, number> | undefined, index = 0, duplicates = 0;
  for await (const row of csvRecords(blob)) {
    if (!map) { map = columns(row); continue; }
    const op = operation(row, map, "single", ++index);
    if (op.company !== company.key) continue;
    const signature = JSON.stringify(op), previous = seen.get(op.id);
    if (previous !== undefined) { if (previous !== signature) throw new Error(`Разные операции имеют одинаковый operation_id: строка ${index}.`); duplicates++; continue; }
    seen.set(op.id, signature); operations.push(op);
    if (operations.length > 10000) throw new Error("В выписке выбранной компании более 10 000 операций. Выберите меньший период.");
  }
  if (!operations.length) throw new Error("У выбранной компании нет операций.");
  operations.sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
  if ((Date.parse(operations.at(-1)!.date) - Date.parse(operations[0].date)) / DAY > 365 * 3) throw new Error("Для одной проверки выберите историю не длиннее трёх лет.");
  return { company, operations, duplicates, from: operations[0].date, to: operations.at(-1)!.date };
}

const quote = (value: string | number | null) => `"${String(value ?? "").replaceAll('"', '""')}"`;
export function operationsCSV(ops: ControlOperation[]) {
  return "operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n" + ops.map(op => [op.id, op.date, op.amount.toFixed(2), op.direction, op.inn, op.counterparty, op.purpose, op.balance?.toFixed(2) ?? ""].map(quote).join(";")).join("\n") + "\n";
}

export async function sha256(blob: Blob | string) {
  const bytes = typeof blob === "string" ? new TextEncoder().encode(blob).buffer : await blob.arrayBuffer();
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(value => value.toString(16).padStart(2, "0")).join("");
}
