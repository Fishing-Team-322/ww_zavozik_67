import test from "node:test";
import assert from "node:assert/strict";
import { ApiClient, ApiError } from "../src/shared/api/client";
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });

test("concurrent expired requests rotate refresh once and preserve JSON bodies", async () => {
  let refreshes = 0;
  let waiting = 0;
  let release!: () => void;
  const barrier = new Promise<void>((resolve) => {
    release = resolve;
  });
  const client = new ApiClient("http://localhost:8080", async (input, init) => {
    const path = new URL(String(input)).pathname;
    assert.equal(init?.credentials, "include");
    assert.equal(init?.redirect, "error");
    if (path === "/v1/auth/login")
      return json({ access_token: "old", expires_at: "2027-01-01T00:00:00Z" });
    if (path === "/v1/auth/refresh") {
      refreshes++;
      return json({ access_token: "new", expires_at: "2027-01-01T00:00:00Z" });
    }
    const authorization = new Headers(init?.headers).get("Authorization");
    if (path === "/v1/me") return json({ id: "owner", companies: [] });
    if (authorization === "Bearer old") {
      waiting++;
      if (waiting === 2) release();
      await barrier;
      return json({ code: "expired", message: "expired" }, 401);
    }
    assert.equal(authorization, "Bearer new");
    assert.equal(init?.body, '{"amount":125.25}');
    return json({ done: true });
  });
  await client.authenticate("login", "owner@example.com", "password");
  const result = await Promise.all([
    client.request("/v1/a", { method: "POST", json: { amount: 125.25 } }),
    client.request("/v1/b", { method: "POST", json: { amount: 125.25 } }),
  ]);
  assert.deepEqual(result, [{ done: true }, { done: true }]);
  assert.equal(refreshes, 1);
});

test("unauthorized response has bounded retries and ends the session", async () => {
  let requests = 0;
  let ended = 0;
  const client = new ApiClient("http://localhost:8080", async (input) => {
    if (String(input).endsWith("/auth/refresh"))
      return json({ access_token: "a" });
    requests++;
    return json({ code: "revoked", message: "Сессия отозвана" }, 401);
  });
  client.onSessionLost(() => {
    ended++;
  });
  await assert.rejects(
    client.request("/v1/me"),
    (error: unknown) => error instanceof ApiError && error.code === "revoked",
  );
  assert.equal(requests, 2);
  assert.equal(ended, 1);
});

test("multipart lets the browser set its boundary; 204 and failures preserve meaning", async () => {
  const client = new ApiClient("http://localhost:8080", async (input, init) => {
    const url = String(input);
    if (url.endsWith("/auth/refresh")) return json({ access_token: "a" });
    if (url.endsWith("/uploads")) {
      assert.ok(init?.body instanceof FormData);
      assert.equal(new Headers(init?.headers).has("Content-Type"), false);
      return json({ id: "job", status: "queued" }, 202);
    }
    if (url.endsWith("/delete")) return new Response(null, { status: 204 });
    return json({ code: "data_required", message: "Загрузите выписку" }, 422);
  });
  const job = await client.upload(
    "company",
    new File(["date,amount"], "statement.csv"),
  );
  assert.equal("id" in job && job.id, "job");
  assert.equal(
    await client.request("/v1/delete", { method: "DELETE" }),
    undefined,
  );
  await assert.rejects(
    client.request("/v1/forecast"),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 422 &&
      error.message === "Загрузите выписку",
  );
  await assert.rejects(client.request("https://another.example/steal"));
});

test("network errors remain visible and canceled requests are not reported as server errors", async () => {
  const client = new ApiClient("http://localhost:8080", async () => {
    throw new TypeError("offline");
  });
  await assert.rejects(
    client.request("/v1/auth/providers", { authenticated: false }),
    (error: unknown) =>
      error instanceof ApiError && error.code === "network_unavailable",
  );
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    client.request("/v1/auth/providers", {
      authenticated: false,
      signal: controller.signal,
    }),
    (error: unknown) =>
      error instanceof DOMException && error.name === "AbortError",
  );
});
