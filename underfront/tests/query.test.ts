import test from "node:test";
import assert from "node:assert/strict";
import { queryParams } from "../src/shared/api/query";

test("optional UUID/boolean filters omit empty values but retain explicit false", () => {
  for (const absent of ["", undefined, null]) {
    const query = queryParams({ counterparty_id: absent, unread: absent });
    assert.equal(query.toString(), "");
  }
  assert.equal(queryParams({ unread: false, limit: 0 }).toString(), "unread=false&limit=0");
  const id = "ab7dbed7-7c44-4bf1-aab5-77dcbb5d3a6d";
  assert.equal(queryParams({ counterparty_id: id, unread: true }).get("counterparty_id"), id);
  assert.equal(queryParams({ q: "Клиент & партнёр" }).get("q"), "Клиент & партнёр");
});
