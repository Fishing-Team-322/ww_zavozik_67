import assert from "node:assert/strict";
import test from "node:test";
import type { Forecast, Schemas } from "../src/shared/api/client";
import { overviewDelayStep, overviewForecastPoints } from "../src/entities/forecast/model/overview-adapters";

const forecast = {
  as_of: "2026-10-24", horizon: 30, opening_balance: 1000,
  points: [{ date: "2026-10-25", p10: 800, p50: 900, p90: 1100 }, { date: "2026-10-26", p10: 700, p50: 850, p90: 1200 }],
} as Forecast;
const comparison = {
  base: forecast,
  scenario: { ...forecast, points: forecast.points.map(point => ({ ...point, p50: point.p50 - 200 })) }, delta: {},
} as Schemas["ScenarioComparison"];

test("overview draws backend scenario values by date and includes the actual opening balance", () => {
  const points = overviewForecastPoints(forecast, comparison, comparison);
  assert.equal(points[0].actual, 1000);
  assert.deepEqual(points.map(point => point.downturn), [1000, 700, 650]);
  assert.deepEqual(points.map(point => point.base), [1000, 900, 850]);
  assert.equal(points[1].p10, 800);
});

test("overview keeps unavailable or stale scenario points unavailable", () => {
  assert.equal(overviewForecastPoints(forecast)[1].downturn, undefined);
  const changed = { ...comparison, base: { ...forecast, opening_balance: 2000 } };
  assert.equal(overviewForecastPoints(forecast, changed)[1].delay, undefined);
  const anotherDate = { ...comparison, scenario: { ...forecast, points: [{ ...forecast.points[0], date: "2026-10-27" }, forecast.points[1]] } };
  assert.equal(overviewForecastPoints(forecast, anotherDate)[1].delay, undefined);
  const revised = { ...comparison, base: { ...forecast, points: forecast.points.map(point => ({ ...point, p50: 1 })) } };
  assert.equal(overviewForecastPoints(forecast, revised)[1].delay, undefined);
});

test("delay preset selects the largest actual future planned receipt and excludes linked or paid aliases", () => {
  const make = (id: string, amount: number, status: string, date = "2026-10-26") => ({ id, amount, status, date, direction: "in", probability: 1, counterparty: { id: "party-"+id, name: id } }) as Schemas["PlannedEvent"];
  const events = [make("past", 100000, "expected", "2026-10-22"), make("paid", 100000, "received"), make("linked", 100000, "linked"), make("small", 100, "expected"), make("large", 200, "expected")];
  assert.deepEqual(overviewDelayStep(events, "2026-10-24", "2026-11-24"), { kind: "delay_counterparty", counterparty_id: "party-large", delay_days: 14 });
  assert.equal(overviewDelayStep([make("paid", 100, "received")], "2026-10-24", "2026-11-24"), null);
  assert.equal(events[0].id, "past");
});
