"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import { useSession } from "@/src/features/auth";
import { api, message, type Schemas } from "@/src/shared/api";
import { useApiResource } from "@/src/shared/api/use-api-resource";
import {
  Button,
  Checkbox,
  Input,
  Select,
  ConfirmDialog,
  EmptyState,
} from "@/src/shared/ui";
import { SectionCard } from "@/src/widgets/cabinet-shell";
import { FinanceState } from "./FinanceState";
import { fieldGrid, money, statusLabel, today } from "./finance-utils";

const kinds = [
  { value: "usn_advance", label: "Аванс УСН" },
  { value: "usn_annual", label: "УСН за год" },
  { value: "vat", label: "НДС за квартал: три платежа" },
  { value: "enp", label: "ЕНП: подтверждённый платёж" },
  { value: "contributions", label: "Страховые взносы: подтверждённый срок" },
  { value: "other", label: "Другой или индивидуальный срок" },
];
export function TaxesScreen() {
  const { company } = useSession();
  const base = `/v1/companies/${company!.id}`;
  const [year, setYear] = useState(new Date().getFullYear());
  const resource = useApiResource<Schemas["TaxOverview"]>(
    `${base}/taxes?year=${year}&months=12`,
  );
  const [draft, setDraft] = useState<Schemas["TaxInput"]>({
    kind: "usn_advance",
    period: "9m",
    year,
    amount: 0,
    title: "Аванс УСН",
    source_ref: "",
    confirmed: false,
    additional: false,
  });
  const requestID = useRef<string | null>(null);
  const [preview, setPreview] = useState<Schemas["TaxDraft"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<Schemas["TaxObligation"] | null>(
    null,
  );
  const manual = ["enp", "contributions", "other"].includes(draft.kind);
  function change(patch: Partial<Schemas["TaxInput"]>) {
    setDraft({ ...draft, ...patch });
    if (Object.keys(patch).length === 1 && "confirmed" in patch) return;
    requestID.current = null;
    setPreview(null);
    setNotice(null);
  }
  async function submit(confirm: boolean) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (confirm) {
        requestID.current ||= crypto.randomUUID();
        await api.request(`${base}/taxes`, {
          method: "POST",
          json: { ...draft, request_id: requestID.current },
        });
        setNotice(
          "Обязательство сохранено. Календарь и прогноз обновятся автоматически.",
        );
        setPreview(null);
        requestID.current = null;
        resource.refresh();
      } else
        setPreview(
          await api.request<Schemas["TaxDraft"]>(`${base}/taxes/preview`, {
            method: "POST",
            json: draft,
          }),
        );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-5">
      <SectionCard className="space-y-4 p-5">
        <h1 className="text-xl font-semibold">Налоги и обязательные платежи</h1>
        <p className="text-sm text-[color:var(--text-secondary)]">
          Сумму берём из подтверждённого расчёта или учётной системы. Календарь
          переносит общие сроки УСН и НДС на рабочий день. Для индивидуальной
          отсрочки укажите свой срок. ЕНП — способ уплаты: не создавайте его
          второй раз поверх того же УСН или НДС.
        </p>
        <Input
          label="Год календаря"
          type="number"
          min="2024"
          max="2027"
          value={year}
          onChange={(e) => {
            const value = Number(e.target.value);
            if (value >= 2024 && value <= 2027) setYear(value);
          }}
        />
        <FinanceState
          loading={resource.loading}
          error={resource.error}
          retry={resource.refresh}
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {resource.data?.calendar.map((rule) => (
            <article
              key={`${rule.kind}:${rule.period}`}
              className="rounded-md border border-[color:var(--border)] p-3 text-sm"
            >
              <p className="font-semibold">
                {kinds.find((k) => k.value === rule.kind)?.label} ·{" "}
                {rule.period} / {rule.year}
              </p>
              <p>{rule.dates.join(" · ")}</p>
              <a
                href={rule.source_url}
                target="_blank"
                rel="noreferrer"
                className="text-[color:var(--accent)] underline"
              >
                Сроки ФНС
              </a>
            </article>
          ))}
        </div>
        {resource.data?.calendar.length === 0 && (
          <p>
            Для этого года календарь ещё не опубликован в приложении. Можно
            указать подтверждённый индивидуальный срок.
          </p>
        )}
      </SectionCard>
      <SectionCard className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Добавить обязательство</h2>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit(false);
          }}
        >
          <div className={fieldGrid}>
            <Select
              label="Вид платежа"
              value={draft.kind}
              options={kinds}
              onChange={(e) =>
                change({
                  kind: e.target.value as Schemas["TaxKind"],
                  period:
                    e.target.value === "usn_annual"
                      ? "year"
                      : e.target.value === "vat"
                        ? "q3"
                        : e.target.value === "usn_advance"
                          ? "9m"
                          : "manual",
                  due_date: ["enp", "contributions", "other"].includes(
                    e.target.value,
                  )
                    ? today()
                    : undefined,
                  title:
                    kinds.find((k) => k.value === e.target.value)?.label ??
                    "Налог",
                })
              }
            />
            <Input
              label="Название обязательства"
              value={draft.title}
              required
              maxLength={500}
              onChange={(e) => change({ title: e.target.value })}
            />
            <Input
              label="Налоговый год"
              type="number"
              value={draft.year}
              required
              min="2024"
              max="2100"
              onChange={(e) => change({ year: Number(e.target.value) })}
            />
            {manual ? (
              <Input
                label="Период / основание"
                value={draft.period}
                required
                maxLength={500}
                onChange={(e) => change({ period: e.target.value })}
              />
            ) : (
              <Select
                label="Период"
                value={draft.period}
                options={
                  draft.kind === "usn_annual"
                    ? [{ value: "year", label: "За год" }]
                    : draft.kind === "vat"
                      ? [
                          { value: "q1", label: "I квартал" },
                          { value: "q2", label: "II квартал" },
                          { value: "q3", label: "III квартал" },
                          { value: "q4", label: "IV квартал" },
                        ]
                      : [
                          { value: "q1", label: "I квартал" },
                          { value: "h1", label: "Полугодие" },
                          { value: "9m", label: "9 месяцев" },
                        ]
                }
                onChange={(e) => change({ period: e.target.value })}
              />
            )}
            <Input
              label="Подтверждённая сумма, ₽"
              type="number"
              min="0.01"
              step="0.01"
              max="10000000000000"
              value={draft.amount || ""}
              required
              onChange={(e) => change({ amount: Number(e.target.value) })}
            />
            {manual && (
              <Input
                label="Подтверждённый срок платежа"
                type="date"
                value={draft.due_date ?? today()}
                required
                onChange={(e) => change({ due_date: e.target.value })}
              />
            )}
            <Input
              label="Откуда получена сумма"
              placeholder="Расчёт бухгалтера, декларация или документ"
              value={draft.source_ref}
              required
              maxLength={500}
              onChange={(e) => change({ source_ref: e.target.value })}
            />
          </div>
          <Checkbox
            label="Это дополнительная сумма сверх обычных налоговых платежей: включить её в прогноз"
            checked={draft.additional}
            onChange={(e) => change({ additional: e.target.checked })}
          />
          <p className="text-xs text-[color:var(--text-secondary)]">
            Обычные повторяющиеся расходы уже входят в базовый прогноз. Без
            этого флажка обязательство видно в календаре и план-факте;
            дополнительного списания в прогнозе не будет.
          </p>
          <Checkbox
            label="Подтверждаю сумму и отсутствие второго обязательства на тот же платёж"
            checked={draft.confirmed}
            onChange={(e) => change({ confirmed: e.target.checked })}
          />
          <Button type="submit" variant="outline" loading={busy}>
            Рассчитать график платежей
          </Button>
          {preview && (
            <div className="space-y-3 rounded-md border border-[color:var(--border)] p-4">
              <p className="font-semibold">Проверьте перед сохранением</p>
              {preview.payments.map((p) => (
                <p key={p.date}>
                  {p.date} · {money(p.amount)}
                </p>
              ))}
              <p className="text-sm">
                {preview.additional
                  ? "Сумма будет добавлена к прогнозу."
                  : "Дополнительного списания в прогнозе не будет."}
              </p>
              <Button
                type="button"
                loading={busy}
                disabled={!draft.confirmed}
                onClick={() => void submit(true)}
              >
                Подтвердить и добавить
              </Button>
            </div>
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
      <SectionCard className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">Сохранённые обязательства</h2>
        {resource.data?.obligations.length === 0 && (
          <EmptyState title="Обязательств пока нет" />
        )}
        {resource.data?.obligations.map((obligation) => (
          <article
            key={obligation.id}
            className="space-y-2 border-b border-[color:var(--border)] pb-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-semibold">
                {obligation.title} · {money(obligation.amount)}
              </h3>
              {obligation.status === "active" ? (
                <Button
                  variant="ghost"
                  disabled={obligation.editable === false || obligation.source === "tax_api"}
                  title={obligation.editable === false || obligation.source === "tax_api" ? "Измените обязательство в учётной системе и синхронизируйте источник" : undefined}
                  onClick={() => setCancelling(obligation)}
                >
                  Отменить оставшиеся платежи
                </Button>
              ) : (
                <span>Отменено</span>
              )}
            </div>
            <p className="text-sm">
              {obligation.source_ref} · оплачено по выписке:{" "}
              {money(obligation.paid_amount)}
            </p>
            {obligation.payments.map((p) => (
              <p key={p.event_id} className="text-sm">
                <Link
                  className="text-[color:var(--accent)] underline"
                  href={`/calendar?date=${p.date}&event=${p.event_id}`}
                >
                  {p.date} · {money(p.amount)} · {statusLabel(p.status)}
                </Link>
              </p>
            ))}
          </article>
        ))}
      </SectionCard>
      <ConfirmDialog
        open={!!cancelling}
        title="Отменить оставшиеся платежи?"
        description="Подтверждённые выпиской оплаты и история обязательства сохранятся."
        loading={busy}
        onCancel={() => {
          if (!busy) setCancelling(null);
        }}
        onConfirm={() => {
          if (!cancelling) return;
          setBusy(true);
          setError(null);
          void api
            .request(`/v1/taxes/${cancelling.id}/cancel`, { method: "POST" })
            .then(() => {
              setCancelling(null);
              resource.refresh();
            })
            .catch((e) => setError(message(e)))
            .finally(() => setBusy(false));
        }}
      />
    </div>
  );
}
