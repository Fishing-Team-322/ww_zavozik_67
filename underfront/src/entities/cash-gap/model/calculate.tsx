import type { CashGapDetails, GapAction, GapCashflowEvent, GapForecast, GapScenario, GapSimulation, WaterfallStep } from "./types";

const DAY = 86_400_000;

function dayStamp(value: string): number {
  const stamp = Date.parse(`${value}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(stamp) || new Date(stamp).toISOString().slice(0, 10) !== value) {
    throw new Error("В сценарии указана некорректная дата.");
  }
  return stamp;
}

export function daysBetween(from: string, to: string): number {
  return Math.round((dayStamp(to) - dayStamp(from)) / DAY);
}

export function formatGapDate(date: string, full = false): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: full ? "long" : "short", ...(full ? { year: "numeric" as const } : {}), timeZone: "UTC" }).format(new Date(`${date}T00:00:00Z`));
}

export function calculateGapForecast(scenario: GapScenario, events: readonly GapCashflowEvent[]): GapForecast {
  const start = dayStamp(scenario.startDate);
  const end = dayStamp(scenario.endDate);
  if (end < start || end - start > 366 * DAY || !Number.isSafeInteger(scenario.openingBalance)) throw new Error("Некорректный период или начальный остаток.");
  const ids = new Set<string>();
  for (const event of events) {
    if (ids.has(event.id) || !Number.isSafeInteger(event.amount)) throw new Error("Проверьте суммы и идентификаторы событий.");
    ids.add(event.id);
    const stamp = dayStamp(event.date);
    // Не скрываем перенесённые обязательства за границами периода симуляции.
    if (stamp < start || stamp > end) throw new Error("Для этого действия нужно расширить период расчёта, чтобы учесть все платежи.");
  }
  const days: GapForecast["days"] = [];
  let balance = scenario.openingBalance;
  for (let stamp = start; stamp <= end; stamp += DAY) {
    const date = new Date(stamp).toISOString().slice(0, 10);
    const daily = events.filter((event) => event.date === date);
    const income = daily.reduce((sum, event) => sum + Math.max(0, event.amount), 0);
    const expense = daily.reduce((sum, event) => sum + Math.max(0, -event.amount), 0);
    const opening = balance;
    balance += income - expense;
    if (!Number.isSafeInteger(balance)) throw new Error("Сумма событий выходит за допустимую точность расчёта.");
    days.push({ date, opening, closing: balance, income, expense });
  }
  const minimum = Math.min(...days.map((day) => day.closing));
  const negative = days.filter((day) => day.closing < 0);
  return { days, minimum, maximumShortfall: Math.max(0, -minimum), shortfallDays: negative.length, firstGapDate: negative[0]?.date ?? null, closing: balance };
}

export function applyGapActions(scenario: GapScenario, actions: readonly GapAction[], actionIds: readonly string[]): GapCashflowEvent[] {
  const selected = new Set(actionIds);
  if (selected.size !== actionIds.length || actionIds.some((id) => !actions.some((action) => action.id === id))) throw new Error("Выбрано неизвестное или повторяющееся действие.");
  let events = scenario.events.map((event) => ({ ...event }));
  for (const action of actions.filter((item) => selected.has(item.id))) {
    if (action.cost && (!Number.isSafeInteger(action.cost.amount) || action.cost.amount < 0)) throw new Error("Некорректная стоимость действия.");
    if (action.conflictsWith.some((id) => selected.has(id))) throw new Error("Отсрочка и рассрочка одного платежа не могут применяться вместе.");
    for (const effect of action.effects) {
      if (effect.kind === "add") {
        events.push(...effect.events.map((event) => ({ ...event })));
        continue;
      }
      const original = events.find((event) => event.id === effect.eventId);
      if (!original) throw new Error("Исходный платёж для действия не найден.");
      if (effect.kind === "move") {
        events = events.map((event) => event.id === original.id ? { ...event, date: effect.date } : event);
      } else {
        if (!effect.parts.length || effect.parts.some((part) => !Number.isSafeInteger(part.amount) || Math.sign(part.amount) !== Math.sign(original.amount)) || effect.parts.reduce((sum, part) => sum + part.amount, 0) !== original.amount) {
          throw new Error("Сумма частей должна совпадать с исходным платежом.");
        }
        events = events.filter((event) => event.id !== original.id);
        events.push(...effect.parts.map((part, index) => ({ ...original, ...part, id: `${original.id}:part-${index + 1}`, title: `${original.title} · часть ${index + 1}` })));
      }
    }
    if (action.cost && action.cost.amount > 0) {
      events.push({ id: `${action.id}:cost`, title: `Стоимость: ${action.title}`, amount: -action.cost.amount, date: action.cost.date, counterparty: action.cost.counterparty, source: "contract", document: action.conditions });
    }
  }
  return events.sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
}

export function buildGapWaterfall(scenario: GapScenario, throughDate: string): WaterfallStep[] {
  let balance = scenario.openingBalance;
  const steps: WaterfallStep[] = [{ id: "opening", title: "Начальный остаток", kind: "opening", amount: balance, before: 0, after: balance }];
  for (const event of [...scenario.events].filter((item) => item.date <= throughDate).sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id))) {
    const before = balance;
    balance += event.amount;
    steps.push({ id: event.id, title: event.title, kind: event.amount >= 0 ? "income" : "expense", amount: event.amount, before, after: balance, event });
  }
  steps.push({ id: "closing", title: "Итоговый остаток", kind: "closing", amount: balance, before: 0, after: balance });
  return steps;
}

export function simulateCashGap(details: CashGapDetails, actionIds: readonly string[]): GapSimulation {
  const { scenario, actions } = details;
  const baseline = calculateGapForecast(scenario, scenario.events);
  const events = applyGapActions(scenario, actions, actionIds);
  const alternative = calculateGapForecast(scenario, events);
  const actionPreviews = actions.map((action) => {
    const preview = calculateGapForecast(scenario, applyGapActions(scenario, actions, [action.id]));
    return { actionId: action.id, improvement: baseline.maximumShortfall - preview.maximumShortfall, maximumShortfall: preview.maximumShortfall, minimum: preview.minimum };
  });
  return {
    actionIds: actions.filter((action) => actionIds.includes(action.id)).map((action) => action.id),
    baseline, alternative, events, actionPreviews,
    waterfall: buildGapWaterfall(scenario, baseline.firstGapDate ?? scenario.endDate),
    totalCost: actions.filter((action) => actionIds.includes(action.id)).reduce((sum, action) => sum + (action.cost?.amount ?? 0), 0),
    // Вероятность альтернативы может вернуть только внешний источник оценки.
    alternativeProbability: actionIds.length ? null : details.probability,
  };
}
