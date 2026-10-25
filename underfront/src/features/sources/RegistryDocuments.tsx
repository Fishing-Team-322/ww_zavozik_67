"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";

import { useCallback, useEffect, useState } from "react";
import { api, message } from "@/src/shared/api";
import { Button, Input, Select } from "@/src/shared/ui";

type RegistryRecord = {
  id?: string; inn: string; ogrn: string; name: string; source: string;
  source_format: string; actual_at: string; registration_status: string;
  signature_status: string; target?: string; created_at?: string;
};
type Preview = { id: string; records: RegistryRecord[] };

export function RegistryDocuments({ companyId, companyINN }: { companyId: string; companyINN: string | null }) {
  const base = `/v1/companies/${companyId}/registry`;
  const [records, setRecords] = useState<RegistryRecord[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [index, setIndex] = useState("0");
  const [target, setTarget] = useState("counterparty");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const reload = useCallback(async () => setRecords(await api.request<RegistryRecord[]>(base)), [base]);
  useEffect(() => {
    const controller = new AbortController();
    void api.request<RegistryRecord[]>(base, { signal: controller.signal }).then(setRecords).catch(cause => { if (!controller.signal.aborted) setError(message(cause)); });
    return () => controller.abort();
  }, [base]);
  async function upload(file: File) {
    setError(""); setNotice(""); setPreview(null);
    if (!file.size || file.size > 16 * 1024 * 1024) { setError("Нужен непустой PDF, XML или ZIP до 16 МиБ."); return; }
    setBusy(true);
    try {
      const form = new FormData(); form.append("file", file);
      const result = await api.request<Preview>(`${base}/preview`, { method: "POST", form });
      setPreview(result); setIndex("0");
      setTarget(result.records[0]?.inn === companyINN ? "company" : "counterparty");
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  const selected = preview?.records[Number(index)];
  async function confirm() {
    if (!preview || busy) return;
    setBusy(true); setError("");
    try {
      await api.request(`${base}/confirm`, { method: "POST", json: { preview_id: preview.id, record_index: Number(index), target } });
      await reload(); setPreview(null); setNotice("Сведения ФНС сохранены. Банковские операции и остатки не изменены."); api.invalidate();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  return <section id="registry-documents" className="min-w-0 space-y-4 rounded-md border border-[color:var(--border)] p-5">
    <ContentHeading level={2} >Документы ФНС · ЕГРЮЛ и ЕГРИП</ContentHeading>
    <ContentText variant="description" tone="muted" >Официальная выписка содержит реквизиты и сведения об организации на дату документа. Это не банковская выписка: операции и остатки из неё не создаются. Ключ DaData не нужен.</ContentText>
    <Input label="Загрузить документ ФНС" type="file" accept=".pdf,.xml,.zip" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ""; }} helperText="PDF с текстовым слоем, XML или ZIP ФНС · до 16 МиБ. Сканы без текстового слоя не поддерживаются." />
    {busy && <p role="status">Обрабатываем документ ФНС…</p>}
    {error && <ContentText variant="body" tone="danger" role="alert" >{error}</ContentText>}
    {notice && <ContentText variant="body" role="status" >{notice}</ContentText>}
    {preview && selected && <div className="space-y-3 rounded-md bg-[color:var(--surface-subtle)] p-4">
      <ContentHeading level={3} >Предпросмотр реквизитов</ContentHeading>
      {preview.records.length > 1 && <Select density="form" label="Организация в документе" value={index} onChange={event => { setIndex(event.target.value); setTarget(preview.records[Number(event.target.value)]?.inn === companyINN ? "company" : "counterparty"); }} options={preview.records.map((record, i) => ({ value: String(i), label: `${record.inn} · ${record.name}` }))} />}
      <RegistryProfile record={selected} />
      <Select density="form" label="Привязать документ" value={target} onChange={event => setTarget(event.target.value)} options={[{ value: "counterparty", label: "Контрагент этого рабочего пространства" }, ...(selected.inn === companyINN ? [{ value: "company", label: "Моя компания · ИНН совпадает" }] : [])]} />
      {selected.inn !== companyINN && <ContentText variant="body" >Для привязки к своей компании сначала укажите совпадающий корректный ИНН в настройках. Совпадение ИНН не подтверждает юридическое владение.</ContentText>}
      <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void confirm()}>Подтвердить и сохранить сведения ФНС</Button><Button variant="ghost" disabled={busy} onClick={() => setPreview(null)}>Отмена</Button></div>
    </div>}
    <ContentHeading level={3} >Сохранённые сведения и история документов</ContentHeading>
    {!records.length && <ContentText variant="description" tone="muted" >Документов ФНС пока нет.</ContentText>}
    {records.map(record => <article key={record.id} className="space-y-2 border-t border-[color:var(--border)] pt-3"><RegistryProfile record={record} /><ContentText variant="meta" >{record.target === "company" ? "Моя компания" : "Контрагент"} · владение не подтверждено · счёт не проверен</ContentText></article>)}
  </section>;
}

export function RegistryProfile({ record }: { record: Pick<RegistryRecord, "name" | "inn" | "ogrn" | "actual_at" | "source_format"> & { registration_status?: string } }) {
  return <div className="space-y-1 text-sm"><p className="font-semibold">{record.name}</p><p>ИНН: {record.inn} · ОГРН / ОГРНИП: {record.ogrn}</p><p>Сведения на: {record.actual_at} · источник: ФНС {record.source_format.toUpperCase()}</p><p>Статус в документе: {record.registration_status || "Не указан"}</p><p>Электронная подпись: не проверена (NOT_VERIFIED). Документ не подтверждает ваши полномочия.</p></div>;
}
