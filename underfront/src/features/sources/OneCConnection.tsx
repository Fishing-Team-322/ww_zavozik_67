"use client";
import { ContentHeading, ContentText } from "@/src/shared/ui/content";

import { useEffect, useRef, useState } from "react";
import { api, message, type Source, type SourceTest } from "@/src/shared/api";
import { Button, Input, Select } from "@/src/shared/ui";
import { validInn } from "@/src/shared/lib/inn";
import { SectionCard } from "@/src/widgets/cabinet-shell";

type Props = {
  companyId: string;
  companyINN: string | null;
  sources: Source[];
  onChanged: () => void;
  onOpenBankImport?: () => void;
};

function testMessage(result: SourceTest) {
  if (result.ready_to_sync) return "Соединение и состав OData проверены.";
  return result.missing?.length
    ? `В 1С не опубликованы: ${result.missing.slice(0, 8).join(", ")}.`
    : result.message || "Подключение требует настройки маппинга.";
}

const sourceStatus = (status: string) => ({ pending: "Ожидает проверки", ok: "Подключено", error: "Ошибка", mapping_required: "Нужна настройка" })[status] ?? status;

export function OneCConnection({ companyId, companyINN, sources, onChanged, onOpenBankImport }: Props) {
  const [address, setAddress] = useState("");
  const [inn, setInn] = useState(companyINN || "");
  const [account, setAccount] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"network" | "file">("network");
  const [foundAccounts, setFoundAccounts] = useState<Array<{ number: string; name: string }>>([]);
  const [discovered, setDiscovered] = useState(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);

  function start(id: string) {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(id);
    setNotice(null);
    setError(null);
    return controller;
  }
  function finish(controller: AbortController) {
    if (!controller.signal.aborted) setBusy(null);
  }
  async function synchronize(id: string, controller: AbortController) {
    const job = await api.syncSource(id, controller.signal);
    setNotice("1С отвечает. Сохраняем операции и счета…");
    const done = await api.waitForJob(job, controller.signal);
    const result = (done.result || {}) as Record<string, unknown>;
    setNotice(
      `Синхронизация завершена. Новых операций: ${result.added ?? "нет данных"}, повторов: ${result.duplicates ?? "нет данных"}; новых счетов: ${result.plans_added ?? "нет данных"}, обновлено: ${result.plans_updated ?? "нет данных"}.`,
    );
    onChanged();
  }
  async function connect(event: React.FormEvent) {
    event.preventDefault();
    if (!validInn(inn.trim())) { setError("Проверьте контрольную цифру ИНН компании."); return; }
    if (!/^\d{20}$/.test(account) || /^0+$/.test(account)) { setError("Выберите найденный счёт или укажите действительный номер из 20 цифр."); return; }
    const controller = start("connect");
    try {
      if (inn.trim() !== companyINN) {
        await api.updateCompany(companyId, { inn: inn.trim() }, controller.signal);
      }
      const source = await api.createSource(
        companyId,
        {
          kind: "onec_odata",
          title: "1С:Бухгалтерия 3.0",
          config: {
            template: "accounting3",
            base_url: address.trim(),
            company_account: account.trim(),
            username: username.trim(),
            password,
          },
        },
        controller.signal,
      );
      setPassword("");
      onChanged();
      const result = await api.testSource(source.id, controller.signal);
      if (!result.ready_to_sync) {
        setNotice(`Источник сохранён. ${testMessage(result)}`);
        onChanged();
        return;
      }
      await synchronize(source.id, controller);
    } catch (cause) {
      if (!controller.signal.aborted) setError(message(cause));
    } finally {
      finish(controller);
    }
  }
  async function discover() {
    if (!validInn(inn.trim())) { setError("Проверьте контрольную цифру ИНН компании."); return; }
    const controller = start("discover");
    try {
      if (inn.trim() !== companyINN) await api.updateCompany(companyId, { inn: inn.trim() }, controller.signal);
      const result = await api.request<{ organizations: Array<{ name: string; inn: string; accounts: Array<{ number: string; name: string }> }> }>(`/v1/companies/${companyId}/onec/discover`, { method: "POST", json: { base_url: address.trim(), username: username.trim(), password }, signal: controller.signal });
      const accounts = result.organizations.flatMap(org => org.accounts);
      setFoundAccounts(accounts); setDiscovered(true); setAccount(accounts[0]?.number ?? "");
      setNotice(accounts.length ? `Найдено счетов: ${accounts.length}. Выберите счёт для подключения. Связь с организацией проверена по справочнику этой 1С; юридическое владение не проверялось.` : "Организация найдена, но её счета не опубликованы. Попросите администратора 1С открыть справочник счетов или используйте файловый импорт.");
      onChanged();
    } catch (cause) { if (!controller.signal.aborted) setError(message(cause)); }
    finally { finish(controller); }
  }
  async function run(id: string, action: "test" | "sync") {
    const controller = start(id);
    try {
      if (action === "test") {
        const result = await api.testSource(id, controller.signal);
        setNotice(testMessage(result));
        onChanged();
      } else await synchronize(id, controller);
    } catch (cause) {
      if (!controller.signal.aborted) setError(message(cause));
    } finally {
      finish(controller);
    }
  }
  return (
    <SectionCard id="onec-connection" className="space-y-4">
      <div>
        <ContentHeading level={2} >Подключить 1С:Бухгалтерию 3.0</ContentHeading>
        <ContentText variant="description" tone="muted" className="mt-1">
          Выберите способ передачи данных. ПУЛЬС читает разрешённые данные, а организацию внутри базы создают и ведут в самой 1С. Один ИНН не открывает доступ к базе.
        </ContentText>
      </div>
      <div className="flex flex-wrap gap-2"><Button type="button" variant={mode === "network" ? "default" : "outline"} onClick={() => setMode("network")}>Подключить 1С по сети</Button><Button type="button" variant={mode === "file" ? "default" : "outline"} onClick={() => setMode("file")}>Импортировать файлы из 1С</Button></div>
      {mode === "file" ? <div className="space-y-3 text-sm"><p>Выгрузите банковскую выписку из 1С в формате 1CClientBankExchange, CSV или XLSX и загрузите её в разделе банковских операций. Адрес OData, логин и пароль для этого не нужны.</p><Button type="button" variant="outline" onClick={() => onOpenBankImport ? onOpenBankImport() : document.querySelector('input[accept=".csv,.xlsx,.txt,.1c"]')?.closest("section")?.scrollIntoView({ behavior: "smooth" })}>Перейти к импорту банковской выписки</Button></div> : <>
      <ol className="list-decimal space-y-1 pl-5 text-sm text-[color:var(--text-secondary)]"><li>Администратор вашей 1С публикует базу на веб-сервере и включает стандартный интерфейс OData. Универсального адреса для всех организаций нет.</li><li>Получите URL публикации и отдельного пользователя с правом чтения. Это адрес сервера, а не API-ключ. Сервер ПУЛЬС должен иметь доступ к адресу; локальная база потребует защищённого подключения и разрешения оператора.</li><li>Укажите адрес и учётную запись, нажмите «Найти организацию и счета», затем выберите найденный счёт.</li></ol>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={connect}>
        {discovered && foundAccounts.length > 0 && <Select density="form" label="Найденный счёт организации" value={account} options={foundAccounts.map(item => ({ value: item.number, label: `${item.number} · ${item.name}` }))} onChange={event => setAccount(event.target.value)} />}
        <Input
          label="ИНН компании"
          required
          inputMode="numeric"
          pattern="[0-9]{10}([0-9]{2})?"
          maxLength={12}
          value={inn}
          onChange={(event) => setInn(event.target.value)}
          disabled={busy !== null}
          helperText="Для поиска организации в базе 1С."
        />
        <Input
          label="Адрес OData 1С"
          type="url"
          required
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="https://example.ru/1c/odata/standard.odata/"
          disabled={busy !== null}
          containerClassName="sm:col-span-2"
        />
        <details className="sm:col-span-2"><summary className="cursor-pointer text-sm">Дополнительно: номер счёта вручную</summary><Input
          label="Расчётный счёт компании"
          required
          inputMode="numeric"
          pattern="[0-9]{20}"
          maxLength={20}
          value={account}
          onChange={(event) => setAccount(event.target.value)}
          helperText="20 цифр. Формат номера не доказывает принадлежность; перед подключением проверим его в справочнике 1С."
          disabled={busy !== null}
        /></details>
        <Input
          label="Логин 1С"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          disabled={busy !== null}
        />
        <Input
          label="Пароль 1С"
          type="password"
          secretToggle
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
          disabled={busy !== null}
        />
        <div className="flex items-end">
          <Button type="button" variant="outline" disabled={busy !== null || !address.trim()} onClick={() => void discover()}>Найти организацию и счета</Button>
        </div>
        <div className="flex items-end">
          <Button type="submit" loading={busy === "connect"} disabled={busy !== null}>
            Подключить и синхронизировать
          </Button>
        </div>
      </form>
      </>}
      <ContentText variant="description" tone="muted" >
        Счета попадут в прогноз только при подтверждённой дате оплаты и связи с
        платежом. Если счета не опубликованы в OData, импортируются доступные
        банковские операции.
      </ContentText>
      {notice && <ContentText variant="body" role="status" >{notice}</ContentText>}
      {error && <ContentText variant="body" tone="danger" role="alert" >{error}</ContentText>}
      {sources.filter((source) => source.kind === "onec_odata").map((source) => (
        <div key={source.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-[color:var(--border)] pt-3 text-sm">
          <div>
            <p className="font-medium">{source.title}</p>
            <p className="text-[color:var(--text-secondary)]">
              {source.status === "ok" ? "Подключено" : source.error || sourceStatus(source.status)}
              {source.last_synced_at ? ` · обновлено ${new Date(source.last_synced_at).toLocaleString("ru-RU")}` : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" disabled={busy !== null} onClick={() => run(source.id, "test")}>Проверить</Button>
            <Button type="button" size="sm" disabled={busy !== null || !source.enabled} loading={busy === source.id} onClick={() => run(source.id, "sync")}>Синхронизировать</Button>
          </div>
        </div>
      ))}
    </SectionCard>
  );
}
