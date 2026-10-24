"use client";
import { useState } from "react";
import { useSession } from "@/src/features/auth";
import {
  api,
  message,
  type Schemas,
  type PlannedEvent,
} from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import { Button, Input, Select } from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { rubles, displayDate } from "@/src/entities/forecast";
import { FinanceState } from "./FinanceState";

const today = () => new Date().toISOString().slice(0, 10);
export function CalendarScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [month, setMonth] = useState(
    (company!.data_as_of || today()).slice(0, 7),
  );
  const asOf = (company!.data_as_of || today()).slice(0, 10);
  const end = new Date(`${month}-01T00:00:00Z`);
  end.setUTCMonth(end.getUTCMonth() + 1);
  const daysAhead = Math.ceil((end.getTime() - Date.parse(asOf)) / 86400000);
  const horizon = daysAhead > 60 ? 90 : daysAhead > 30 ? 60 : 30;
  const calendar = useApiResource<Schemas["Calendar"]>(
    `${base}/calendar?month=${month}&horizon=${horizon}`,
  );
  const [phrase, setPhrase] = useState("");
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(today());
  const [amount, setAmount] = useState("");
  const [direction, setDirection] = useState<"in" | "out">("out");
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const reset = () => {
    setEditing(null);
    setTitle("");
    setAmount("");
    setName("");
  };
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const input: Schemas["CreateEventInput"] = {
      title,
      date,
      amount: Number(amount),
      direction,
      ...(name.trim() ? { counterparty_name: name.trim() } : {}),
    };
    try {
      if (editing) await api.updateEvent(editing, input);
      else await api.createEvent(company!.id, input);
      reset();
      calendar.refresh();
      setNotice("Событие сохранено. Прогноз учтёт изменения.");
    } catch (error) {
      setError(message(error));
    } finally {
      setBusy(false);
    }
  }
  function edit(event: PlannedEvent) {
    setEditing(event.id);
    setTitle(event.title);
    setAmount(String(event.amount));
    setDate(event.date);
    setDirection(event.direction);
    setName(event.counterparty.name);
    setError(null);
  }
  return (
    <div className="grid min-w-0 grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
      <SectionCard className="min-w-0 p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-lg font-semibold">Платёжный календарь</h2>
          <Input
            type="month"
            aria-label="Месяц календаря"
            containerClassName="w-full sm:w-auto"
            value={month}
            onChange={(event) => {
              if (event.target.value) setMonth(event.target.value);
            }}
          />
        </div>
        <FinanceState
          loading={calendar.loading}
          error={calendar.error}
          retry={calendar.refresh}
        />
        <div className="max-w-full overflow-x-auto">
          <table className="w-full min-w-[600px] text-left text-sm">
            <thead>
              <tr className="border-b border-[color:var(--border)]">
                <th className="p-3">Дата</th>
                <th className="p-3">Планы и источник</th>
                <th className="p-3">Остаток по прогнозу</th>
              </tr>
            </thead>
            <tbody>
              {calendar.data?.days.map((day) => (
                <tr
                  key={day.date}
                  className={`border-b border-[color:var(--border)] ${day.risk === "danger" ? "bg-[color:var(--danger-soft)]" : ""}`}
                >
                  <td className="whitespace-nowrap p-3">
                    {displayDate(day.date)}
                    {!day.is_workday && (
                      <p className="text-xs text-[color:var(--text-secondary)]">
                        Выходной
                      </p>
                    )}
                  </td>
                  <td className="p-3">
                    {day.events.length
                      ? day.events.map((event) => (
                          <div key={event.id} className="mb-3 space-y-1">
                            <p>
                              {event.title} ·{" "}
                              {event.direction === "in" ? "+" : "−"}
                              {rubles(event.amount)}
                            </p>
                            <p className="text-xs text-[color:var(--text-secondary)]">
                              {event.counterparty.name} · {event.source} ·{" "}
                              {event.status === "missed"
                                ? "Просрочен"
                                : event.status === "received"
                                  ? "Получен"
                                  : event.status === "cancelled"
                                    ? "Отменён"
                                    : "Ожидается"}
                            </p>
                            {event.editable && (
                              <div className="flex gap-3">
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => edit(event)}
                                >
                                  Изменить
                                </Button>
                                {event.source === "manual" && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={async () => {
                                      setError(null);
                                      try {
                                        await api.deleteEvent(event.id);
                                        calendar.refresh();
                                        if (editing === event.id) reset();
                                      } catch (error) {
                                        setError(message(error));
                                      }
                                    }}
                                  >
                                    Удалить
                                  </Button>
                                )}
                              </div>
                            )}
                          </div>
                        ))
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap p-3 tabular-nums">
                    {day.balance_p50 === null
                      ? "Нет оценки"
                      : rubles(day.balance_p50)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
      <SectionCard className="min-w-0 space-y-4 p-5">
        <h2 className="text-lg font-semibold">
          {editing ? "Изменить событие" : "Добавить событие"}
        </h2>
        <div className="space-y-3">
          <Input
            label="Опишите платёж"
            placeholder="Клиент заплатит 300 тысяч 20-го"
            value={phrase}
            onChange={(event) => setPhrase(event.target.value)}
            maxLength={500}
          />
          <Button
            variant="outline"
            disabled={!phrase || busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const draft = await api.request<Schemas["CreateEventInput"]>(
                  `${base}/events/parse`,
                  { method: "POST", json: { text: phrase } },
                );
                setTitle(draft.title);
                setDate(draft.date);
                setAmount(String(draft.amount));
                setDirection(draft.direction);
                setName(draft.counterparty_name || "");
                setEditing(null);
                setNotice("Проверьте распознанные поля перед сохранением.");
              } catch (error) {
                setError(message(error));
              } finally {
                setBusy(false);
              }
            }}
          >
            Заполнить по описанию
          </Button>
        </div>
        <form className="space-y-3" onSubmit={submit}>
          <Input
            label="Название платежа"
            value={title}
            required
            maxLength={200}
            onChange={(event) => setTitle(event.target.value)}
          />
          <Input
            label="Контрагент"
            value={name}
            maxLength={200}
            onChange={(event) => setName(event.target.value)}
          />
          <Input
            label="Дата платежа"
            type="date"
            value={date}
            required
            onChange={(event) => setDate(event.target.value)}
          />
          <Input
            label="Сумма, ₽"
            type="number"
            min="0.01"
            max="10000000000000"
            step="0.01"
            value={amount}
            required
            onChange={(event) => setAmount(event.target.value)}
          />
          <Select
            label="Направление"
            value={direction}
            options={[
              { value: "in", label: "Поступление" },
              { value: "out", label: "Списание" },
            ]}
            onChange={(event) =>
              setDirection(event.target.value as "in" | "out")
            }
          />
          <Button type="submit" loading={busy}>
            Сохранить событие
          </Button>
          {editing && (
            <Button type="button" variant="ghost" onClick={reset}>
              Отменить редактирование
            </Button>
          )}
        </form>
        {error && (
          <p role="alert" className="text-sm text-[color:var(--danger)]">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm">
            {notice}
          </p>
        )}
      </SectionCard>
    </div>
  );
}
