import test from "node:test";
import assert from "node:assert/strict";
import { ApiClient, ApiError } from "../src/shared/api/client";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
for (const failure of ["network", "server"] as const) {
  test(`temporary ${failure} refresh failure keeps the session recoverable`, async () => {
    let refreshes = 0, losses = 0;
    const client = new ApiClient("http://localhost:8080", async (input, init) => {
      const path = new URL(String(input)).pathname;
      if (path === "/v1/auth/login") return json({ access_token: "old" });
      if (path === "/v1/auth/refresh") {
        refreshes++;
        if (refreshes === 1) {
          if (failure === "network") throw new TypeError("temporary offline");
          return json({ code: "busy", message: "temporary unavailable" }, 503);
        }
        return json({ access_token: "new" });
      }
      if (path === "/v1/me") return json({ id: "synthetic-owner", companies: [] });
      if (new Headers(init?.headers).get("Authorization") === "Bearer old")
        return json({ code: "expired", message: "expired" }, 401);
      return json({ ok: true });
    });
    client.onSessionLost(() => losses++);
    await client.authenticate("login", "synthetic@example.invalid", "Synthetic-only-password");
    losses = 0;
    await assert.rejects(client.request("/v1/companies"),
      (e: unknown) => e instanceof ApiError && e.status === (failure === "network" ? 0 : 503));
    const recovered = await client.request<{ ok: boolean }>("/v1/companies");
    assert.equal(losses, 0, "temporary errors must not revoke the local session");
    assert.equal(refreshes, 2, "retry refresh after connectivity recovers");
    assert.equal(recovered.ok, true);
  });
}
