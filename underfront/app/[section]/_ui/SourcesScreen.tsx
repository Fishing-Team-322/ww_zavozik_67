"use client";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/src/features/auth";
import { api, message, type Schemas, type Job } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Select } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";

type ImportReport = {
  id: string;
  added: number;
  duplicates: number;
  status: string;
  started_at: string;
  errors: Array<{ row?: number; code?: string; message: string }>;
};
export function SourcesScreen() {
  const { company, reload } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const sources = useApiResource<Schemas["Source"][]>(`${base}/sources`);
  const imports = useApiResource<ImportReport[]>(`${base}/imports`);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [upload, setUpload] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  async function finish(job: Job, signal: AbortSignal) {
    setNotice("Файл принят. Обрабатываем операции…");
    const done = await api.waitForJob(job, signal);
    if (!done.result_ref)
      throw new Error(
        "В результате обработки нет отчёта. Проверьте историю загрузок.",
      );
    const report = await api.request<ImportReport>(done.result_ref, { signal });
    setUpload(null);
    setNotice(
      `Добавлено операций: ${report.added}. Повторных строк: ${report.duplicates}. Ошибок строк: ${report.errors.length}.`,
    );
    sources.refresh();
    imports.refresh();
    await reload();
  }
  async function sendFile(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    if (file.size > 4 * 1024 * 1024) {
      setError("Максимальный размер файла — 4 MiB.");
      return;
    }
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError(null);
    setNotice(null);
    setUpload(null);
    try {
      const result = await api.upload(company!.id, file, controller.signal);
      if ("upload_id" in result) {
        setUpload(result.upload_id);
        setNotice(
          "Укажите, какие столбцы содержат дату, сумму и направление платежа.",
        );
      } else await finish(result, controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) setError(message(error));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  async function map(mapping: Record<string, string>) {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true);
    setError(null);
    try {
      const job = await api.request<Job>(`/v1/uploads/${upload}/mapping`, {
        method: "POST",
        json: { mapping },
        signal: controller.signal,
      });
      await finish(job, controller.signal);
    } catch (error) {
      if (!controller.signal.aborted) setError(message(error));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="space-y-5">
      <SectionCard className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Загрузить банковскую выписку</h2>
        <p className="text-sm text-[color:var(--text-secondary)]">
          CSV или XLSX до 4 MiB. Для прогноза нужен остаток на конец дня. При
          неизвестных заголовках можно сопоставить столбцы вручную.
        </p>
        <form className="space-y-4" onSubmit={sendFile}>
          <label htmlFor="statement-file" className="block text-sm font-medium">
            Файл выписки
          </label>
          <input
            id="statement-file"
            type="file"
            disabled={busy}
            required
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="block max-w-full text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-[color:var(--accent-soft)] file:px-4 file:py-2 file:font-semibold file:text-[color:var(--accent)]"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <Button type="submit" loading={busy} disabled={!file}>
            Загрузить выписку
          </Button>
        </form>
        {notice && (
          <p role="status" className="text-sm">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-[color:var(--danger)]">
            {error}
          </p>
        )}
        {upload && <MappingEditor upload={upload} busy={busy} onMap={map} />}
      </SectionCard>
      <SectionCard className="space-y-3 p-5">
        <h2 className="text-lg font-semibold">Источники компании</h2>
        <FinanceState
          loading={sources.loading}
          error={sources.error}
          retry={sources.refresh}
        />
        {sources.data?.length === 0 && (
          <p className="text-sm text-[color:var(--text-secondary)]">
            Источники пока не подключены.
          </p>
        )}
        {sources.data?.map((source) => (
          <div
            key={source.id}
            className="flex flex-wrap justify-between gap-3 border-b border-[color:var(--border)] py-3 text-sm"
          >
            <p>
              {source.title} · {source.kind}
            </p>
            <p>
              {source.status === "ok"
                ? "Данные загружены"
                : source.status === "error"
                  ? source.error || "Ошибка источника"
                  : source.status}{" "}
              · операций: {source.records}
            </p>
          </div>
        ))}
      </SectionCard>
      <SectionCard className="space-y-3 p-5">
        <h2 className="text-lg font-semibold">История загрузок</h2>
        <FinanceState
          loading={imports.loading}
          error={imports.error}
          retry={imports.refresh}
        />
        {imports.data?.length === 0 && (
          <p className="text-sm text-[color:var(--text-secondary)]">
            Загрузок ещё не было.
          </p>
        )}
        {imports.data?.map((report) => (
          <div
            key={report.id}
            className="border-b border-[color:var(--border)] py-3 text-sm"
          >
            <p>
              {new Date(report.started_at).toLocaleString("ru-RU")} · добавлено{" "}
              {report.added}, повторов {report.duplicates}, ошибок{" "}
              {report.errors.length}
            </p>
            {report.errors.slice(0, 10).map((issue, index) => (
              <p
                key={index}
                className="mt-1 text-xs text-[color:var(--danger)]"
              >
                {issue.row ? `Строка ${issue.row}: ` : ""}
                {issue.message}
              </p>
            ))}
          </div>
        ))}
      </SectionCard>
    </div>
  );
}
function MappingEditor({
  upload,
  busy,
  onMap,
}: {
  upload: string;
  busy: boolean;
  onMap: (mapping: Record<string, string>) => Promise<void>;
}) {
  const preview = useApiResource<Schemas["UploadPreview"]>(
    `/v1/uploads/${upload}/preview`,
  );
  return (
    <>
      <FinanceState
        loading={preview.loading}
        error={preview.error}
        retry={preview.refresh}
      />
      {preview.data && (
        <MappingForm
          key={upload}
          preview={preview.data}
          busy={busy}
          onMap={onMap}
        />
      )}
    </>
  );
}
function MappingForm({
  preview,
  busy,
  onMap,
}: {
  preview: Schemas["UploadPreview"];
  busy: boolean;
  onMap: (mapping: Record<string, string>) => Promise<void>;
}) {
  const [mapping, setMapping] = useState<Record<string, string>>(
    preview.proposed_mapping,
  );
  const fields = [
    ["date", "Дата"],
    ["amount", "Сумма"],
    ["direction", "Направление (in/out)"],
    ["sign", "Сумма со знаком вместо направления"],
    ["counterparty", "Контрагент"],
    ["inn", "ИНН"],
    ["purpose", "Назначение"],
    ["balance", "Остаток на конец дня"],
  ];
  return (
    <div className="space-y-4 border-t border-[color:var(--border)] pt-4">
      <h3 className="font-semibold">Сопоставление столбцов</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map(([key, label]) => (
          <Select
            key={key}
            label={label}
            value={mapping[key] || ""}
            disabled={busy}
            onChange={(event) =>
              setMapping({ ...mapping, [key]: event.target.value })
            }
            options={[
              { value: "", label: "Не указан" },
              ...preview.columns.map((value) => ({ value, label: value })),
            ]}
          />
        ))}
      </div>
      <div className="max-h-48 overflow-auto">
        <table className="text-left text-xs">
          <thead>
            <tr>
              {preview.columns.map((column, index) => (
                <th key={index} className="p-2">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preview.rows.slice(0, 5).map((row, index) => (
              <tr key={index}>
                {row.map((cell, index) => (
                  <td key={index} className="max-w-56 truncate p-2">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button
        disabled={
          !mapping.date ||
          !mapping.amount ||
          !(mapping.direction || mapping.sign)
        }
        loading={busy}
        onClick={() =>
          onMap(
            Object.fromEntries(
              Object.entries(mapping).filter(([, value]) => value !== ""),
            ),
          )
        }
      >
        Подтвердить и обработать
      </Button>
    </div>
  );
}
