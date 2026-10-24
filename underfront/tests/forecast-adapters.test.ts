import test from "node:test";
import assert from "node:assert/strict";
import { chartDays, calendarEvent, fallbackNotice } from "../src/entities/forecast";
import type { Forecast, PlannedEvent } from "../src/shared/api";

test("fallback notice distinguishes data support from a service outage", () => {
  assert.match(fallbackNotice(["out_of_domain_naive_fallback"]), /характер операций/);
  assert.doesNotMatch(fallbackNotice(["out_of_domain_naive_fallback"]), /недоступна/);
  assert.match(fallbackNotice(["ml_service_fallback"]), /недоступна/);
});

test("chart keeps unknown history and missing scenario points as unknown", () => {
  const forecast = {
    history: [
      { date: "2026-10-22", balance: null },
      { date: "2026-10-23", balance: 100 },
    ],
    points: [{ date: "2026-10-24", p10: -20, p50: 50, p90: 200 }],
    markers: [{ date: "2026-10-24", title: "Аренда" }],
  } as Forecast;
  const days = chartDays(forecast, {
    points: [
      { date: "2026-10-24", p10: -50, p50: -10, p90: 100, is_workday: true },
    ],
  });
  assert.equal(days[0].actual, null);
  assert.equal(days[0].baseline, undefined);
  assert.equal(days[1].scenario, undefined);
  assert.deepEqual(days[2], {
    date: "2026-10-24",
    baseline: 50,
    lowerBound: -20,
    upperBound: 200,
    scenario: -10,
    events: ["Аренда"],
  });
});

test("event conversion keeps server ownership and maps direction/status explicitly", () => {
  const event = {
    id: "event",
    amount: 123.45,
    title: "Invoice",
    date: "2026-10-24",
    direction: "in",
    status: "missed",
    counterparty: { id: "cp", name: "Клиент" },
    source: "invoice",
    editable: false,
    probability: 0.6,
    category: "other",
  } as PlannedEvent;
  const view = calendarEvent(event);
  assert.equal(view.direction, "income");
  assert.equal(view.status, "overdue");
  assert.equal(view.manual, false);
  assert.equal(view.editable, false);
  assert.equal(view.probability, 0.6);
});
