import type { CashGapDetails } from "@/src/entities/cash-gap";

/** Один фиксированный срез: вероятность предоставлена mock-сервисом, а не вычислена UI. */
export const CASH_GAP_DEMO: CashGapDetails = {
  probability: 64,
  probabilitySource: "mock",
  scenario: {
    id: "gap-november-2026", companyId: "puls-demo", asOf: "2026-11-01",
    startDate: "2026-11-01", endDate: "2026-11-30", openingBalance: 470_000,
    openingSource: "Банковская выписка · остаток на 1 ноября 2026",
    events: [
      { id: "client-alpha", title: "Оплата клиента Альфа", counterparty: "ООО Альфа", date: "2026-11-03", amount: 150_000, source: "invoice", document: "Счёт № 142 от 20.10.2026" },
      { id: "payroll", title: "Выплата зарплаты", counterparty: "Команда · 12 сотрудников", date: "2026-11-05", amount: -300_000, source: "bank", document: "Зарплатный реестр № 11", note: "Обязательный платёж по утверждённому графику." },
      { id: "tax", title: "Налоги и взносы", counterparty: "ФНС", date: "2026-11-06", amount: -250_000, source: "tax", document: "Демонстрационное налоговое обязательство" },
      { id: "rent", title: "Аренда офиса", counterparty: "БЦ Каскад", date: "2026-11-08", amount: -120_000, source: "recurring", document: "Договор аренды № 18", note: "Варианты отсрочки и рассрочки требуют согласования с арендодателем." },
      { id: "service", title: "Продление аналитики", counterparty: "DataFlow", date: "2026-11-08", amount: -30_000, source: "manual", document: "Заявка финансового менеджера № 38", note: "Необязательное продление; в демо допустим перенос до 19 ноября." },
      { id: "client-beta", title: "Оплата клиента Бета", counterparty: "ООО Бета", date: "2026-11-10", amount: 240_000, source: "contract", document: "Договор № 57 · этап 2" },
      { id: "supplier", title: "Расчёт с поставщиком", counterparty: "ТехноСнаб", date: "2026-11-12", amount: -100_000, source: "invoice", document: "Счёт № 208" },
      { id: "client-gamma", title: "Оплата клиента Гамма", counterparty: "ООО Гамма", date: "2026-11-18", amount: 260_000, source: "contract", document: "Договор № 63 · завершение работ" },
    ],
  },
  actions: [
    { id: "accelerate-client", title: "Получить оплату клиента раньше", description: "Перенести 240 000 ₽ от Беты с 10 на 7 ноября. В демо учтена скидка 1% отдельным списанием.", conditions: "Требуется согласие клиента; скидка 2 400 ₽ удерживается 7 ноября.", effects: [{ kind: "move", eventId: "client-beta", date: "2026-11-07" }], cost: { amount: 2_400, date: "2026-11-07", counterparty: "ООО Бета" }, conflictsWith: [] },
    { id: "defer-rent", title: "Договориться об отсрочке аренды", description: "Перенести все 120 000 ₽ с 8 на 11 ноября — после оплаты Беты.", conditions: "Условие демо: арендодатель согласует перенос без комиссии.", effects: [{ kind: "move", eventId: "rent", date: "2026-11-11" }], cost: { amount: 0, date: "2026-11-11", counterparty: "БЦ Каскад" }, conflictsWith: ["split-rent"] },
    { id: "split-rent", title: "Разбить аренду на две части", description: "Вместо 120 000 ₽ 8 ноября — по 60 000 ₽ 8 и 16 ноября. Общая сумма сохраняется.", conditions: "Условие демо: две части без доплаты, по соглашению с арендодателем.", effects: [{ kind: "split", eventId: "rent", parts: [{ date: "2026-11-08", amount: -60_000 }, { date: "2026-11-16", amount: -60_000 }] }], cost: { amount: 0, date: "2026-11-08", counterparty: "БЦ Каскад" }, conflictsWith: ["defer-rent"] },
    { id: "defer-service", title: "Отложить необязательное продление", description: "Перенести 30 000 ₽ за аналитику с 8 на 19 ноября. Расход остаётся в прогнозе.", conditions: "Условие демо: сервис допускает отсрочку продления без штрафа.", effects: [{ kind: "move", eventId: "service", date: "2026-11-19" }], cost: { amount: 0, date: "2026-11-19", counterparty: "DataFlow" }, conflictsWith: [] },
    { id: "financing", title: "Использовать краткосрочное финансирование", description: "Получить 100 000 ₽ 7 ноября; вернуть 100 000 ₽ и заплатить 5 000 ₽ 25 ноября.", conditions: "Вымышленные условия для симуляции. Это не предложение банка; возврат и полная стоимость включены в ноябрь.", effects: [{ kind: "add", events: [
      { id: "loan-in", title: "Получение финансирования", counterparty: "Демо-финансирование", date: "2026-11-07", amount: 100_000, source: "contract", document: "Mock-условия: 100 000 ₽ до 25 ноября" },
      { id: "loan-out", title: "Возврат финансирования", counterparty: "Демо-финансирование", date: "2026-11-25", amount: -100_000, source: "contract", document: "Mock-условия: возврат основного долга" },
    ] }], cost: { amount: 5_000, date: "2026-11-25", counterparty: "Демо-финансирование" }, conflictsWith: [] },
  ],
};
