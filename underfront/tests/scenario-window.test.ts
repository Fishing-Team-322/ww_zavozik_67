import test from "node:test";
import assert from "node:assert/strict";
import { scenarioWindowBounds, shiftScenarioDate } from "../src/entities/forecast/model/scenario-window";

test("scenario window is 30 inclusive UTC dates, including month and year boundaries", () => {
  const first = "2026-10-25", last = "2027-01-22";
  assert.deepEqual(scenarioWindowBounds(first, last, ""), { from: first, to: "2026-11-23", valid: true, latestStart: "2026-12-24", earliestEnd: "2026-11-23" });
  assert.equal(scenarioWindowBounds(first, last, "2026-12-24").to, last);
  assert.equal(scenarioWindowBounds(first, last, "2026-12-25").valid, false);
  assert.equal(scenarioWindowBounds(first, last, "2026-10-24").valid, false);
  assert.equal(shiftScenarioDate("2026-11-23", -29), first);
  assert.equal(shiftScenarioDate("2026-02-30", 29), "");
  assert.equal(scenarioWindowBounds("", "", "").valid, false);
});
