"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useSession } from "@/src/features/auth";
import { api, message, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Input, Select, Button, Dialog, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { rubles, displayDate } from "@/src/entities/forecast";
import { FinanceState } from "./FinanceState";

export function TransactionsScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const searchParams = useSearchParams();
  const counterpartyId = searchParams.get("counterparty_id") ?? "";
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [source, setSource] = useState("");
  const [rule, setRule] = useState<Schemas["Operation"] | null>(null);
  const [ruleCategory, setRuleCategory] = useState<Schemas["Category"]>("other");
  const [applyTo, setApplyTo] = useState("future"); const [notice, setNotice] = useState("");
  const sources = useApiResource<Schemas["Source"][]>(`${base}/sources`);
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
  const filters = new URLSearchParams({ q: search, direction, category, from, to, source, counterparty_id: counterpartyId });
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
      <div className="grid gap-3 sm:grid-cols-3"><Input label="С даты" type="date" value={from} max={to || undefined} onChange={e => { setFrom(e.target.value); reset(); }} /><Input label="По дату" type="date" value={to} min={from || undefined} onChange={e => { setTo(e.target.value); reset(); }} /><Select label="Источник" value={source} options={[{ value: "", label: "Все" }, ...Array.from(new Set((sources.data ?? []).map(x => x.kind))).map(kind => ({ value: kind, label: kind }))]} onChange={e => { setSource(e.target.value); reset(); }} /></div>
      {counterpartyId && <Link href="/transactions" className="text-[color:var(--accent)] underline">Сбросить фильтр контрагента</Link>}
      {notice && <p role="status">{notice}</p>}
      <FinanceState
        loading={rows.loading}
        error={rows.error || summary.error || categories.error || sources.error || error}
        retry={() => { rows.refresh(); summary.refresh(); categories.refresh(); sources.refresh(); }}
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
      {summary.data && <details className="text-sm"><summary className="cursor-pointer">Сводка по категориям</summary><p className="my-2 text-xs text-[color:var(--text-secondary)]">Внутренние переводы исключены из поступлений и списаний. Переводы: {rubles(summary.data.internal_total)}.</p><Table><TableHeader><TableRow><TableHead>Категория</TableHead><TableHead>Пришло</TableHead><TableHead>Ушло</TableHead><TableHead>Операций</TableHead></TableRow></TableHeader><TableBody>{summary.data.by_category.map(row => <TableRow key={row.category}><TableCell>{categories.data?.find(c => c.key === row.category)?.title ?? row.category}</TableCell><TableCell>{rubles(row.in)}</TableCell><TableCell>{rubles(row.out)}</TableCell><TableCell>{row.count}</TableCell></TableRow>)}</TableBody></Table></details>}
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
                    <p>{row.counterparty.id ? <Link className="text-[color:var(--accent)] underline" href={`/counterparties/${row.counterparty.id}`}>{row.counterparty.name}</Link> : row.counterparty.name || "Без контрагента"}</p><p className="text-xs">Источник: {row.source}</p>
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
                      disabled={busy}
                      onChange={async (event) => {
                        setBusy(true); setError(null);
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
                        } finally { setBusy(false); }
                      }}
                    />
                    {row.counterparty.id && <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setRule(row); setRuleCategory(row.category); }}>Правило для контрагента</Button>}
                    <p className="text-xs text-[color:var(--text-secondary)]">{row.category_method === "manual" ? "Указана вручную" : "Определена автоматически"}</p>
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
      <Dialog open={!!rule} title="Категория операций контрагента" onClose={() => setRule(null)} dismissDisabled={busy}><div className="space-y-4"><p>{rule?.counterparty.name}</p><Select label="Категория" value={ruleCategory} options={(categories.data ?? []).map(c => ({ value: c.key, label: c.title }))} onChange={e => setRuleCategory(e.target.value as Schemas["Category"])} /><Select label="Применить" value={applyTo} options={[{ value: "future", label: "К будущим операциям" }, { value: "all", label: "К существующим и будущим" }]} onChange={e => setApplyTo(e.target.value)} />{error && <p role="alert">{error}</p>}<Button loading={busy} onClick={async () => { if (!rule?.counterparty.id) return; setBusy(true); setError(null); try { await api.request(`${base}/operations/recategorize`, { method: "POST", json: { counterparty_id: rule.counterparty.id, category: ruleCategory, apply_to: applyTo } }); setRule(null); setNotice("Правило категории сохранено."); } catch (cause) { setError(message(cause)); } finally { setBusy(false); } }}>Применить правило</Button></div></Dialog>
    </SectionCard>
  );
}
