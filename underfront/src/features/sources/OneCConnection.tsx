"use client";

import { useEffect, useRef, useState } from "react";
import { api, message, type Source, type SourceTest } from "@/src/shared/api";
import { Button, Input } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";

type Props = {
  companyId: string;
  companyINN: string | null;
  sources: Source[];
  onChanged: () => void;
};

function testMessage(result: SourceTest) {
  if (result.ready_to_sync) return "Соединение и состав OData проверены.";
  return result.missing?.length
    ? `В 1С не опубликованы: ${result.missing.slice(0, 8).join(", ")}.`
    : result.message || "Подключение требует настройки маппинга.";
}

const sourceStatus = (status: string) => ({ pending: "Ожидает проверки", ok: "Подключено", error: "Ошибка", mapping_required: "Нужна настройка" })[status] ?? status;

export function OneCConnection({ companyId, companyINN, sources, onChanged }: Props) {
  const [address, setAddress] = useState("");
  const [inn, setInn] = useState(companyINN || "");
  const [account, setAccount] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    <SectionCard className="space-y-4 p-5">
      <div>
        <h2 className="text-lg font-semibold">Подключить 1С:Бухгалтерию 3.0</h2>
        <p className="mt-1 text-sm text-[color:var(--text-secondary)]">
          Укажите опубликованный стандартный OData, номер счёта вашей компании и
          учётную запись 1С с правом чтения. Сервис подберёт организацию, счета и
          валюту по данным самой 1С. Адрес должен быть доступен серверу приложения.
        </p>
      </div>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={connect}>
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
        <Input
          label="Расчётный счёт компании"
          required
          inputMode="numeric"
          pattern="[0-9]{20}"
          maxLength={20}
          value={account}
          onChange={(event) => setAccount(event.target.value)}
          helperText="20 цифр; счёт должен принадлежать указанной организации."
          disabled={busy !== null}
        />
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
          <Button type="submit" loading={busy === "connect"} disabled={busy !== null}>
            Подключить и синхронизировать
          </Button>
        </div>
      </form>
      <p className="text-xs text-[color:var(--text-secondary)]">
        Счета попадут в прогноз только при подтверждённой дате оплаты и связи с
        платежом. Если счета не опубликованы в OData, импортируются доступные
        банковские операции.
      </p>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {error && <p role="alert" className="text-sm text-[color:var(--danger)]">{error}</p>}
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
