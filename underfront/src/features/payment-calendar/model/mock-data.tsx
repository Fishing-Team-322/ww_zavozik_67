import { addDays, dateKey, monthStart } from "@/src/entities/payment";
import type { PaymentEvent } from "@/src/entities/payment";

export const DEMO_OPENING_BALANCE = 370_000;
/** Даты привязаны к текущему месяцу, чтобы кнопка «Сегодня» всегда открывала наполненный календарь. */
export function createMockPayments(today: Date): PaymentEvent[] {
  const base = monthStart(today);
  const lastDay = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
  const on = (day: number) => dateKey(addDays(base, Math.min(day, lastDay) - 1));
  return [
    { id: "evt-1", title: "Оплата по договору № 42", counterparty: "Клиент Альфа", amount: 420_000, date: on(3), direction: "income", category: "Клиенты", source: "CRM · Альфа", probability: 90, status: on(3) <= dateKey(today) ? "received" : "expected", manual: false },
    { id: "evt-2", title: "Аренда офиса", counterparty: "БЦ Каскад", amount: 180_000, date: on(5), direction: "expense", category: "Аренда", source: "Банк · автоплатёж", status: on(5) <= dateKey(today) ? "received" : "expected", manual: false },
    { id: "evt-3", title: "Счёт за интеграцию", counterparty: "Клиент Бета", amount: 310_000, date: on(9), direction: "income", category: "Клиенты", source: "CRM · Бета", probability: 75, status: on(9) < dateKey(today) ? "overdue" : "expected", manual: false },
    { id: "evt-4", title: "Аванс команде", counterparty: "Сотрудники", amount: 510_000, date: on(12), direction: "expense", category: "Зарплата", source: "Зарплатный реестр", status: on(12) < dateKey(today) ? "received" : "expected", manual: false },
    { id: "evt-5", title: "Поставка оборудования", counterparty: "ТехноСнаб", amount: 270_000, date: on(16), direction: "expense", category: "Подрядчики", source: "1С · счёт 148", status: on(16) < dateKey(today) ? "received" : "expected", manual: false },
    { id: "evt-6", title: "Подписка на платформу", counterparty: "Клиент Гамма", amount: 560_000, date: on(18), direction: "income", category: "Клиенты", source: "CRM · Гамма", probability: 65, status: on(18) < dateKey(today) ? "overdue" : "expected", manual: false },
    { id: "evt-7", title: "НДС и страховые взносы", counterparty: "ФНС", amount: 690_000, date: on(21), direction: "expense", category: "Налоги", source: "Налоговый календарь", status: on(21) < dateKey(today) ? "overdue" : "expected", manual: false },
    { id: "evt-8", title: "Закрытие этапа работ", counterparty: "Клиент Дельта", amount: 380_000, date: on(23), direction: "income", category: "Клиенты", source: "CRM · Дельта", probability: 80, status: on(23) < dateKey(today) ? "overdue" : "expected", manual: false },
    { id: "evt-9", title: "Облачная инфраструктура", counterparty: "CloudHost", amount: 95_000, date: on(25), direction: "expense", category: "Сервисы", source: "Банк · автоплатёж", status: "expected", manual: false },
    { id: "evt-10", title: "Финальный расчёт", counterparty: "Клиент Эпсилон", amount: 470_000, date: on(27), direction: "income", category: "Клиенты", source: "CRM · Эпсилон", probability: 50, status: "expected", manual: false },
    { id: "evt-11", title: "Зарплата за месяц", counterparty: "Сотрудники", amount: 720_000, date: on(29), direction: "expense", category: "Зарплата", source: "Зарплатный реестр", status: "expected", manual: false },
    { id: "evt-12", title: "Сервис аналитики", counterparty: "DataFlow", amount: 46_000, date: on(11), direction: "expense", category: "Сервисы", source: "Вручную", status: on(11) < dateKey(today) ? "received" : "expected", manual: true },
    { id: "evt-13", title: "Аренда офиса", counterparty: "БЦ Каскад", amount: 180_000, date: dateKey(addDays(base, 35)), direction: "expense", category: "Аренда", source: "Банк · автоплатёж", status: "expected", manual: false },
    { id: "evt-14", title: "Продление контракта", counterparty: "Клиент Альфа", amount: 620_000, date: dateKey(addDays(base, 39)), direction: "income", category: "Клиенты", source: "CRM · Альфа", probability: 70, status: "expected", manual: false },
  ];
}
