"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";
import { queryParams } from "@/src/shared/api/query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Settings2, SlidersHorizontal } from "lucide-react";
import { useSession } from "@/src/features/auth";
import { api, message, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Input, SearchInput, Select, Button, Badge, Dialog, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/src/shared/ui";
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
  const [editingCategory, setEditingCategory] = useState<Schemas["Operation"] | null>(null);
  const [operationCategory, setOperationCategory] = useState<Schemas["Category"]>("other");
  const [applyTo, setApplyTo] = useState("future"); const [notice, setNotice] = useState("");
  const sources = useApiResource<Schemas["Source"][]>(`${base}/sources`);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("");
  const [category, setCategory] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const filtersRef = useRef<HTMLDivElement>(null);
  const [draftFilters, setDraftFilters] = useState({ direction: "", category: "", from: "", to: "", source: "" });
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<Array<string | null>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query), 300);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    if (!advancedOpen) return;
    const closeOutside = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || filtersRef.current?.contains(target) || target.closest('[role="listbox"]')) return;
      setAdvancedOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !(event.target instanceof Element && event.target.closest('[role="listbox"]'))) setAdvancedOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [advancedOpen]);
  const filters = queryParams({ q: search, direction, category, from, to, source, counterparty_id: counterpartyId });
  const page = new URLSearchParams(filters);
  page.set("limit", "5");
  if (cursor) page.set("cursor", cursor);
  const rows = useApiResource<Schemas["OperationPage"]>(
    `${base}/operations?${page}`,
  );
  const summary = useApiResource<Schemas["OperationsSummary"]>(
    `${base}/operations/summary?${filters}`,
  );
  const operationPage = previous.length + 1;
  const activeFilterCount = [direction, category, from, to, source].filter(Boolean).length;
  const hasTotal = typeof rows.data?.total === "number" && Number.isFinite(rows.data.total) && rows.data.total >= 0;
  const operationTotalPages = hasTotal ? Math.max(1, Math.ceil(rows.data!.total / 5)) : operationPage + (rows.data?.next_cursor ? 1 : 0);
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
    <SectionCard className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ContentHeading level={1} >История операций</ContentHeading>
        <Button variant="outline" loading={busy} onClick={exportFile}>
          Выгрузить XLSX
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-full sm:max-w-sm sm:flex-1">
          <SearchInput
            label="Поиск по операциям"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              reset();
            }}
            placeholder="Контрагент или назначение"
          />
        </div>
        <div ref={filtersRef} className="relative shrink-0">
          <Button variant="outline" className="!h-[40px] !px-3 gap-2 [&>svg]:!size-4" aria-expanded={advancedOpen} aria-controls="transaction-filters" onClick={() => { if (!advancedOpen) setDraftFilters({ direction, category, from, to, source }); setAdvancedOpen(value => !value); }}>
            <SlidersHorizontal aria-hidden="true" />Фильтры{activeFilterCount > 0 && <Badge variant="brand" size="sm">Активно: {activeFilterCount}</Badge>}
          </Button>
          {advancedOpen && <div id="transaction-filters" className="absolute right-0 top-full z-30 mt-2 max-h-[min(70vh,560px)] w-[min(420px,calc(100vw-32px))] overflow-y-auto rounded-[6px] border border-[color:var(--border)] bg-[color:var(--surface-elevated)] p-4 shadow-[var(--shadow-md)]">
            <div className="grid gap-3 sm:grid-cols-2">
              <Select density="form" label="Направление" value={draftFilters.direction} onChange={event => setDraftFilters(value => ({ ...value, direction: event.target.value }))} options={[{ value: "", label: "Все" }, { value: "in", label: "Поступления" }, { value: "out", label: "Списания" }]} />
              <Select density="form" label="Категория" value={draftFilters.category} onChange={event => setDraftFilters(value => ({ ...value, category: event.target.value }))} options={[{ value: "", label: "Все категории" }, ...(categories.data || []).map(item => ({ value: item.key, label: item.title }))]} />
              <Input label="С даты" type="date" value={draftFilters.from} max={draftFilters.to || undefined} onChange={event => setDraftFilters(value => ({ ...value, from: event.target.value }))} />
              <Input label="По дату" type="date" value={draftFilters.to} min={draftFilters.from || undefined} onChange={event => setDraftFilters(value => ({ ...value, to: event.target.value }))} />
              <Select density="form" label="Источник" value={draftFilters.source} options={[{ value: "", label: "Все" }, ...Array.from(new Set((sources.data ?? []).map(item => item.kind))).map(kind => ({ value: kind, label: kind }))]} onChange={event => setDraftFilters(value => ({ ...value, source: event.target.value }))} />
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
              <Button variant="ghost" onClick={() => setDraftFilters({ direction: "", category: "", from: "", to: "", source: "" })}>Сбросить фильтры</Button>
              <div className="flex gap-2"><Button variant="outline" onClick={() => setAdvancedOpen(false)}>Отмена</Button><Button onClick={() => { setDirection(draftFilters.direction); setCategory(draftFilters.category); setFrom(draftFilters.from); setTo(draftFilters.to); setSource(draftFilters.source); reset(); setAdvancedOpen(false); }}>Применить</Button></div>
            </div>
          </div>}
        </div>
      </div>
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
            Поступления: <ContentText as="span" variant="financial">{rubles(summary.data.total_in)}</ContentText>
          </p>
          <p>
            Списания: <ContentText as="span" variant="financial">{rubles(summary.data.total_out)}</ContentText>
          </p>
          <p>
            Чистый поток: <ContentText as="span" variant="financial">{rubles(summary.data.net)}</ContentText>
          </p>
        </div>
      )}
      {rows.data && (
        <div className="overflow-x-auto">
          <Table density="compact" pagination={{
            page: operationPage,
            totalPages: operationTotalPages,
            label: hasTotal ? `${operationPage}/${operationTotalPages}` : `${operationPage}/…`,
            disabled: rows.loading,
            onPageChange: (nextPage) => {
              if (nextPage < previous.length + 1) {
                setCursor(previous.at(-1) ?? null);
                setPrevious(previous.slice(0, -1));
              } else if (rows.data.next_cursor) {
                setPrevious([...previous, cursor]);
                setCursor(rows.data.next_cursor);
              }
            },
          }}>
            <TableHeader>
              <TableRow>
                {["Дата", "Контрагент / назначение", "Сумма", "Категория"].map(
                  (label) => (
                    <TableHead numeric={label === "Сумма"} key={label}>
                      {label}
                    </TableHead>
                  ),
                )}
                <TableHead aria-label="Открыть контрагента" className="w-10 px-2" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.data.items.map((row) => (
                <TableRow
                  key={row.id}
                  href={row.counterparty.id ? `/counterparties/${row.counterparty.id}` : undefined}
                  hrefLabel={`Открыть контрагента ${row.counterparty.name}`}
                >
                  <TableCell className="whitespace-nowrap">
                    {displayDate(row.date)}
                  </TableCell>
                  <TableCell className="min-w-48">
                    <p className={row.counterparty.id ? "text-[color:var(--accent)] underline" : undefined}>{row.counterparty.name || "Без контрагента"}</p><ContentText variant="meta">Источник: {row.source}</ContentText>
                    <ContentText variant="description" className="mt-1 max-w-lg">
                      {row.purpose}
                    </ContentText>
                    {row.is_internal && (
                      <ContentText variant="meta">Внутренний перевод</ContentText>
                    )}
                  </TableCell>
                  <TableCell numeric className="whitespace-nowrap">
                    {row.direction === "in" ? "+" : "−"}
                    {rubles(row.amount)}
                  </TableCell>
                  <TableCell className="min-w-48">
                    <div className="flex items-start gap-2">
                      <Button variant="outline" size="icon" className="relative z-10 mt-0.5 !size-5 shrink-0 border !border-[color:var(--accent)] !text-[color:var(--accent)] hover:!bg-[color:var(--accent-soft)] [&>svg]:!size-3.5" aria-label={`Изменить категорию операции ${row.id}`} title="Изменить категорию" disabled={busy} onClick={() => { setEditingCategory(row); setOperationCategory(row.category); setError(null); }}><Settings2 aria-hidden="true" /></Button>
                      <div>
                        <p className="font-medium leading-6">{categories.data?.find(item => item.key === row.category)?.title ?? row.category}</p>
                        <ContentText variant="meta">{row.category_method === "manual" ? "Указана вручную" : "Определена автоматически"}</ContentText>
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {rows.data.items.length === 0 && (
            <ContentText variant="description" tone="muted" className="p-5">
              Операций по выбранным условиям нет.
            </ContentText>
          )}
        </div>
      )}
      {summary.data && <section className="space-y-2" aria-label="Сводка по категориям">
        <ContentHeading level={2}>Сводка по категориям</ContentHeading>
        <ContentText variant="description" tone="muted">Внутренние переводы исключены из поступлений и списаний. Переводы: {rubles(summary.data.internal_total)}.</ContentText>
        <Table><TableHeader><TableRow><TableHead>Категория</TableHead><TableHead numeric>Пришло</TableHead><TableHead numeric>Ушло</TableHead><TableHead numeric>Операций</TableHead></TableRow></TableHeader><TableBody>{summary.data.by_category.map(row => <TableRow key={row.category}><TableCell>{categories.data?.find(item => item.key === row.category)?.title ?? row.category}</TableCell><TableCell numeric>{rubles(row.in)}</TableCell><TableCell numeric>{rubles(row.out)}</TableCell><TableCell numeric>{row.count}</TableCell></TableRow>)}</TableBody></Table>
      </section>}
      <Dialog open={!!editingCategory} title="Категория операции" onClose={() => setEditingCategory(null)} dismissDisabled={busy} className="max-w-sm">
        <form className="space-y-4" onSubmit={async event => {
          event.preventDefault();
          if (!editingCategory) return;
          setBusy(true); setError(null);
          try {
            await api.request(`/v1/operations/${encodeURIComponent(editingCategory.id)}`, { method: "PATCH", json: { category: operationCategory } });
            setEditingCategory(null);
            rows.refresh(); summary.refresh();
          } catch (cause) { setError(message(cause)); }
          finally { setBusy(false); }
        }}>
          <Select density="form" label="Категория" value={operationCategory} options={(categories.data ?? []).map(item => ({ value: item.key, label: item.title }))} onChange={event => setOperationCategory(event.target.value as Schemas["Category"])} />
          {error && <p role="alert" className="text-sm text-[color:var(--danger)]">{error}</p>}
          <div className="flex flex-wrap items-center justify-between gap-2">
            {editingCategory?.counterparty.id ? <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => { setRule(editingCategory); setRuleCategory(operationCategory); setEditingCategory(null); setError(null); }}>Правило для контрагента</Button> : <span />}
            <Button type="submit" disabled={operationCategory === editingCategory?.category} loading={busy}>Сохранить</Button>
          </div>
        </form>
      </Dialog>
      <Dialog open={!!rule} title="Категория операций контрагента" onClose={() => setRule(null)} dismissDisabled={busy}><div className="space-y-4"><p>{rule?.counterparty.name}</p><Select density="form" label="Категория" value={ruleCategory} options={(categories.data ?? []).map(c => ({ value: c.key, label: c.title }))} onChange={e => setRuleCategory(e.target.value as Schemas["Category"])} /><Select density="form" label="Применить" value={applyTo} options={[{ value: "future", label: "К будущим операциям" }, { value: "all", label: "К существующим и будущим" }]} onChange={e => setApplyTo(e.target.value)} />{error && <p role="alert">{error}</p>}<Button loading={busy} onClick={async () => { if (!rule?.counterparty.id) return; setBusy(true); setError(null); try { await api.request(`${base}/operations/recategorize`, { method: "POST", json: { counterparty_id: rule.counterparty.id, category: ruleCategory, apply_to: applyTo } }); setRule(null); setNotice("Правило категории сохранено."); rows.refresh(); summary.refresh(); } catch (cause) { setError(message(cause)); } finally { setBusy(false); } }}>Применить правило</Button></div></Dialog>
    </SectionCard>
  );
}
