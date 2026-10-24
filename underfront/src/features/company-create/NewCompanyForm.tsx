"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { companyApi, type LegalForm, type TaxRegime } from "@/src/entities/company";
import { useCompany } from "@/src/features/company-context/CompanyProvider";
import { Button } from "@/src/shared/ui/button";
import { Input } from "@/src/shared/ui/input";
import { Select } from "@/src/shared/ui/select";

const taxOptions = [
  { value: "usn6", label: "УСН 6% · доходы" },
  { value: "usn15", label: "УСН 15% · доходы минус расходы" },
  { value: "osno", label: "ОСНО" },
  { value: "eshn", label: "ЕСХН" },
  { value: "unknown", label: "Пока не знаю" },
];

export function NewCompanyForm() {
  const router = useRouter();
  const { reloadCompanies, status } = useCompany();
  const [inn, setInn] = useState("");
  const [name, setName] = useState("");
  const [legalForm, setLegalForm] = useState<LegalForm>("ООО");
  const [industry, setIndustry] = useState("");
  const [taxRegime, setTaxRegime] = useState<TaxRegime>("unknown");
  const [reserve, setReserve] = useState("0");
  const [lookupState, setLookupState] = useState<"idle" | "searching" | "found" | "unavailable">("idle");
  const [lookupMessage, setLookupMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const autoFilled = useRef<{ name: string; industry: string }>({ name: "", industry: "" });

  function changeInn(value: string) {
    const next = value.replace(/\D/g, "");
    if (next === inn) return;
    const previousAuto = autoFilled.current;
    setName(current => previousAuto.name && current === previousAuto.name ? "" : current);
    setIndustry(current => previousAuto.industry && current === previousAuto.industry ? "" : current);
    autoFilled.current = { name: "", industry: "" };
    setLookupState("idle");
    setInn(next);
  }

  useEffect(() => {
    if (inn.length !== 10 && inn.length !== 12) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLookupState("searching");
      try {
        const result = await companyApi.lookupInn(inn, controller.signal);
        if (controller.signal.aborted) return;
        setName(current => { if (!current && result.name) { autoFilled.current.name = result.name; return result.name; } return current; });
        setIndustry(current => { if (!current && result.industry) { autoFilled.current.industry = result.industry; return result.industry; } return current; });
        if (result.legal_form === "ООО" || result.legal_form === "ИП") setLegalForm(result.legal_form);
        if (taxOptions.some(option => option.value === result.tax_regime)) setTaxRegime(result.tax_regime as TaxRegime);
        setLookupMessage(result.source ? `Найдено в ${result.source}. Проверьте данные перед сохранением.` : "Данные найдены. Проверьте их перед сохранением.");
        setLookupState("found");
      } catch (cause) {
        if (controller.signal.aborted) return;
        setLookupMessage(cause instanceof Error ? cause.message : "Поиск по ИНН недоступен");
        setLookupState("unavailable");
      }
    }, 450);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [inn]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const amount = Number(reserve.replace(",", "."));
    if (!Number.isFinite(amount) || amount < 0 || !/^\d+(?:[.,]\d{1,2})?$/.test(reserve)) { setError("Укажите неснижаемый остаток в рублях, до двух знаков после запятой."); return; }
    if (inn && !/^\d{10}(?:\d{2})?$/.test(inn)) { setError("ИНН должен содержать 10 или 12 цифр."); return; }
    setSaving(true);
    let created = false;
    try {
      const company = await companyApi.create({ name: name.trim(), inn: inn || null, legal_form: legalForm, industry: industry.trim(), tax_regime: taxRegime, reserve: amount });
      created = true;
      await reloadCompanies(company.id);
      router.push("/sources");
    } catch (cause) {
      if (created) router.push("/sources");
      else setError(cause instanceof Error ? cause.message : "Не удалось создать компанию");
    } finally { setSaving(false); }
  }

  return <section className="w-full max-w-[560px] text-[color:var(--text-primary)]">
    <header className="border-b border-[color:var(--border)] pb-5"><h1 className="text-[20px] font-semibold tracking-tight">Новая компания</h1><p className="mt-1 text-[13px] text-[color:var(--text-secondary)]">Добавьте реквизиты, чтобы подключить банковские данные и источники.</p></header>
    {status === "unauthorized" && <p className="mt-5 rounded-[5px] border border-[color:var(--border)] p-3 text-[13px]">Для создания компании нужно <Link href="/login" className="font-medium text-[color:var(--accent)] underline">войти в аккаунт</Link>.</p>}
    <form onSubmit={submit} className="mt-5 space-y-5">
      <div><Input label="ИНН" inputMode="numeric" autoComplete="off" maxLength={12} value={inn} onChange={event => changeInn(event.target.value)} placeholder="10 или 12 цифр" className="h-9"/><p className="mt-1 text-[12px] text-[color:var(--text-secondary)]" role="status">{lookupState === "searching" ? "Ищем сведения по ИНН…" : lookupState === "found" || lookupState === "unavailable" ? `${lookupMessage} Форму можно заполнить вручную.` : "После ввода ИНН попробуем заполнить реквизиты автоматически."}</p></div>
      <Input label="Название компании" required maxLength={300} value={name} onChange={event => setName(event.target.value)} className="h-9"/>
      <div className="grid gap-4 sm:grid-cols-2"><Select label="Организационно-правовая форма" size="lg" options={[{ value: "ООО", label: "ООО" }, { value: "ИП", label: "ИП" }]} value={legalForm} onChange={event => setLegalForm(event.target.value as LegalForm)}/><Select label="Налоговый режим" size="lg" options={taxOptions} value={taxRegime} onChange={event => setTaxRegime(event.target.value as TaxRegime)}/></div>
      <Input label="Вид деятельности" required maxLength={120} value={industry} onChange={event => setIndustry(event.target.value)} className="h-9" placeholder="Например, оптовая торговля"/>
      <Input label="Неснижаемый остаток, ₽" required inputMode="decimal" value={reserve} onChange={event => setReserve(event.target.value)} className="h-9" helperText="Сумма, которую нужно сохранять на счетах."/>
      {error && <p role="alert" className="text-[13px] text-[color:var(--danger)]">{error}</p>}
      <div className="flex flex-wrap gap-2 border-t border-[color:var(--border)] pt-5"><Button type="submit" size="lg" disabled={saving || status === "unauthorized"} className="px-4">{saving ? "Сохраняем…" : "Создать компанию"}</Button><Button type="button" size="lg" variant="ghost" onClick={() => router.back()}>Отмена</Button></div>
    </form>
  </section>;
}
