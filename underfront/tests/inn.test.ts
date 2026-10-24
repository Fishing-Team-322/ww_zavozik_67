import test from "node:test";
import assert from "node:assert/strict";
import { validInn } from "../src/shared/lib/inn";

test("INN uses checksum and does not confuse a mistyped official registry identifier", () => {
  assert.equal(validInn("6164138513"), true);
  for (const value of ["6164138512", "0000000000", "6164138513 ", "0", "616413851X"]) assert.equal(validInn(value), false, value);
  assert.equal(validInn("7725895601"), true);
});
