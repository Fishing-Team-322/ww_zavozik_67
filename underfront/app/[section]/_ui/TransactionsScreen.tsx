"use client";
import { useEffect, useState } from "react";
import { useSession } from "@/src/features/auth";
import { api, message, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Input, Select, Button } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { rubles, displayDate } from "@/src/entities/forecast";
import { FinanceState } from "./FinanceState";

export function TransactionsScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("");
  const [category, setCategory] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Array<string | null>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query), 300);
    return () => clearTimeout(timer);
  }, [query]);
  const filters = new URLSearchParams({ q: search, direction, category });
  const page = new URLSearchParams(filters);
  page.set("limit", "50");
  if (cursor) page.set("cursor", cursor);
  const rows = useApiResource<Schemas["OperationPage"]>(
    `${base}/operations?${page}`,
  );
  const summary = useApiResource<Schemas["OperationsSummary"]>(
    `${base}/operations/summary?${filters}`,
  );
  const categories =
    useApiResource<Array<{ key: Schemas["Category"]; title: string }>>(
      "/v1/categories",
    );
  const reset = () => {
    setCursor(null);
    setPrevious([]);
  };
  async function exportFile() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.download(
        `${base}/operations/export?${filters}&format=xlsx`,
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "operations.xlsx";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <SectionCard className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">История операций</h2>
        <Button variant="outline" loading={busy} onClick={exportFile}>
          Выгрузить XLSX
        </Button>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Input
          label="Поиск по операциям"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            reset();
          }}
          placeholder="Контрагент или назначение"
        />
        <Select
          label="Направление"
          value={direction}
          onChange={(event) => {
            setDirection(event.target.value);
            reset();
          }}
          options={[
            { value: "", label: "Все" },
            { value: "in", label: "Поступления" },
            { value: "out", label: "Списания" },
          ]}
        />
        <Select
          label="Категория"
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            reset();
          }}
          options={[
            { value: "", label: "Все категории" },
            ...(categories.data || []).map((c) => ({
              value: c.key,
              label: c.title,
            })),
          ]}
        />
      </div>
      <FinanceState
        loading={rows.loading}
        error={rows.error || error}
        retry={rows.refresh}
      />
      {summary.data && (
        <div className="flex flex-wrap gap-5 text-sm">
          <p>
            Поступления: <strong>{rubles(summary.data.total_in)}</strong>
          </p>
          <p>
            Списания: <strong>{rubles(summary.data.total_out)}</strong>
          </p>
          <p>
            Чистый поток: <strong>{rubles(summary.data.net)}</strong>
          </p>
        </div>
      )}
      {rows.data && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border)] text-xs text-[color:var(--text-secondary)]">
                {["Дата", "Контрагент / назначение", "Сумма", "Категория"].map(
                  (label) => (
                    <th className="p-3" key={label}>
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.data.items.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-[color:var(--border)]"
                >
                  <td className="whitespace-nowrap p-3">
                    {displayDate(row.date)}
                  </td>
                  <td className="min-w-48 p-3">
                    <p>{row.counterparty.name || "Без контрагента"}</p>
                    <p className="mt-1 max-w-lg text-xs text-[color:var(--text-secondary)]">
                      {row.purpose}
                    </p>
                    {row.is_internal && (
                      <p className="text-xs">Внутренний перевод</p>
                    )}
                  </td>
                  <td className="whitespace-nowrap p-3 tabular-nums">
                    {row.direction === "in" ? "+" : "−"}
                    {rubles(row.amount)}
                  </td>
                  <td className="min-w-48 p-3">
                    <Select
                      aria-label={`Категория операции ${row.id}`}
                      value={row.category}
                      options={(categories.data || []).map((c) => ({
                        value: c.key,
                        label: c.title,
                      }))}
                      onChange={async (event) => {
                        setError(null);
                        try {
                          await api.request(
                            `/v1/operations/${encodeURIComponent(row.id)}`,
                            {
                              method: "PATCH",
                              json: { category: event.target.value },
                            },
                          );
                          rows.refresh();
                          summary.refresh();
                        } catch (error) {
                          setError(message(error));
                        }
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.data.items.length === 0 && (
            <p className="p-5 text-sm text-[color:var(--text-secondary)]">
              Операций по выбранным условиям нет.
            </p>
          )}
        </div>
      )}
      <div className="flex gap-3">
        <Button
          variant="outline"
          disabled={!previous.length || rows.loading}
          onClick={() => {
            setCursor(previous.at(-1) || null);
            setPrevious(previous.slice(0, -1));
          }}
        >
          Назад
        </Button>
        <Button
          variant="outline"
          disabled={!rows.data?.next_cursor || rows.loading}
          onClick={() => {
            setPrevious([...previous, cursor]);
            setCursor(rows.data!.next_cursor);
          }}
        >
          Следующая страница
        </Button>
      </div>
    </SectionCard>
  );
}
