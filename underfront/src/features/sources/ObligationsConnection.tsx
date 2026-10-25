"use client";
import { useState } from "react";
import { api, message, type Schemas } from "@/src/shared/api";
import { Button, Input, Select } from "@/src/shared/ui";

export function ObligationsConnection({ companyId, onChanged }: { companyId: string; onChanged: () => void }) {
  const [kind, setKind] = useState("bank_api");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  return <form className="space-y-4" onSubmit={async event => {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const source = await api.request<Schemas["Source"]>(`/v1/companies/${companyId}/sources`, { method: "POST", json: { kind, title: kind === "bank_api" ? "Банк · будущие обязательства" : "Учёт · налоговые обязательства", config: { url, token } } });
      setToken(""); onChanged();
      await api.testSource(source.id);
      await api.waitForJob(await api.syncSource(source.id));
      onChanged(); setNotice("Обязательства загружены в календарь и прогноз. Проверьте их даты, суммы и источник.");
    } catch (cause) { setError(message(cause)); onChanged(); }
    finally { setBusy(false); }
  }}>
    <p>Загрузите кредитные графики, зарплату, будущие поручения или подтверждённые налоги через настроенный учётный шлюз. Понадобится адрес вашего провайдера и токен чтения; оператор сервиса должен разрешить подключение к этому адресу.</p>
    <p className="text-sm">Будущие обязательства сразу участвуют в прогнозе. Демонстрационный шлюз помечает данные «Демо». Сервис не исполняет платежи.</p>
    <Select density="form" label="Тип обязательств" value={kind} onChange={event => setKind(event.target.value)} options={[{ value: "bank_api", label: "Банк: кредиты, зарплата, поручения" }, { value: "tax_api", label: "Учёт: подтверждённые налоги" }]} />
    <Input label="Адрес учётного шлюза" type="url" required value={url} onChange={event => setUrl(event.target.value)} />
    <Input label="Токен чтения шлюза" type="password" autoComplete="off" required value={token} onChange={event => setToken(event.target.value)} />
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button type="submit" loading={busy}>Проверить и загрузить обязательства</Button>
  </form>;
}
