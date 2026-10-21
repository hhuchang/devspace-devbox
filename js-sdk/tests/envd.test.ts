import { afterEach, describe, expect, it } from "vitest";
import { Envd } from "../src/envd.js";
import { Transport } from "../src/internal/transport.js";
import { mockAgent } from "./helpers.js";

describe("Envd", () => {
  let agent: ReturnType<typeof mockAgent> | undefined;
  afterEach(async () => agent?.close());

  it("reads metrics, envs and health", async () => {
    agent = mockAgent();
    const pool = agent.get("https://runtime.example.test");
    const headers = { cookie: "relay_token=connect-token", "e2b-sandbox-id": "sbx-1" };
    pool.intercept({ path: "/metrics", method: "GET", headers }).reply(200, {
      ts: 1_763_000_000,
      cpu_count: 2,
      cpu_used_pct: 8.25,
      mem_total: 1_024,
      mem_used: 512,
      mem_cache: 128,
      disk_total: 2_048,
      disk_used: 1_024,
    });
    pool.intercept({ path: "/envs", method: "GET", headers }).reply(200, {
      DEVBOX_ID: "sbx-1",
      DEVBOX_TEMPLATE_ID: "tpl-1",
    });
    pool
      .intercept({ path: "/health", method: "GET", headers })
      .reply(204, "", { headers: { "X-Envd-Version": "1.2.3" } });

    const envd = new Envd(
      async () =>
        new Transport("https://runtime.example.test", {
          dispatcher: agent,
          headers,
        }),
    );

    await expect(envd.getMetrics()).resolves.toMatchObject({
      cpuCount: 2,
      cpuUsedPct: 8.25,
      memTotal: 1_024,
      diskUsed: 1_024,
    });
    await expect(envd.getEnvs()).resolves.toEqual({
      DEVBOX_ID: "sbx-1",
      DEVBOX_TEMPLATE_ID: "tpl-1",
    });
    await expect(envd.health()).resolves.toEqual({ envdVersion: "1.2.3" });
    agent.assertNoPendingInterceptors();
  });
});
