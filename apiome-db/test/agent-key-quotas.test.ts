/**
 * Structural assertions over the agent key quota migration (#4538, AGX-3.2).
 *
 * V272 adds per-tier agent key limits and the two SQL functions both services read. DB-free
 * contract tests pin its four rules:
 *
 *   1. **Caps follow the license tier** (`tenant_licenses` → `licenses.seats`, Free fallback).
 *   2. **Zero or negative means unlimited** (NULL from `agent_key_quota`).
 *   3. **One count of calls made**: `agent_key_call_count` reads `agent_invocations` for the UTC
 *      day without `quota_rejected` refusals, which is what the AGX-3.3 rollup reports as
 *      `calls - quota_rejections`.
 *   4. **Seeds are fill-if-absent**.
 *
 * These must stay in lock-step with apiome-mcp's `apiome_mcp.agent_quotas` (enforcement) and
 * apiome-rest's `app.agent_keys.get_agent_key_usage` (reporting).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V272__agent_key_quotas_agx_3_2.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

/**
 * The body of one `CREATE OR REPLACE FUNCTION`, up to its `language` clause.
 *
 * @param name The function name.
 * @returns The lower-cased, whitespace-collapsed function source.
 */
function functionBody(name: string): string {
  const start = ddl.indexOf(`create or replace function ${name}(`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(" language ", start));
}

describe("agent key quotas migration (AGX-3.2)", () => {
  it("is present in scripts/ and ordered after the agent invocations migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V271__agent_invocations_agx_3_3.sql"));
  });

  it("targets the apiome schema and creates no table", () => {
    expect(sql.toLowerCase()).toContain("set search_path to apiome, public");
    expect(ddl).not.toContain("create table");
  });

  describe("rules 1 and 2 — caps follow the tier; zero or negative is unlimited", () => {
    it("resolves the tenant's license through tenant_licenses with Free fallbacks", () => {
      const body = functionBody("agent_key_quota");
      expect(body).toContain("left join apiome.tenant_licenses tl on tl.tenant_id = t.tenant_id");
      expect(body).toContain("left join apiome.licenses l on l.id = tl.license_id");
      expect(body).toContain("jsonb_typeof(l.seats -> 'agent_key_rps') = 'number'");
      expect(body).toContain("else 2 end as rps");
      expect(body).toContain("else 1000 end as daily_calls");
    });

    it("returns NULL for an unlimited cap", () => {
      const body = functionBody("agent_key_quota");
      expect(body).toContain("case when rps > 0 then rps end");
      expect(body).toContain("case when daily_calls > 0 then daily_calls::bigint end");
    });

    it("is a read-only function", () => {
      expect(ddl).toMatch(/agent_key_quota\(p_tenant_id uuid\)[\s\S]*?\$\$ language sql stable;/);
      expect(ddl).toMatch(/agent_key_call_count\(p_key_id uuid, p_day date\)[\s\S]*?\$\$ language sql stable;/);
    });
  });

  describe("rule 3 — one count of calls made", () => {
    it("counts the key's invocations on the UTC day, without refusals", () => {
      const body = functionBody("agent_key_call_count");
      expect(body).toContain("from apiome.agent_invocations i");
      expect(body).toContain("i.key_id = p_key_id");
      expect(body).toContain("i.invoked_at >= (p_day::timestamp at time zone 'utc')");
      expect(body).toContain("i.invoked_at < ((p_day + 1)::timestamp at time zone 'utc')");
      expect(body).toContain("i.outcome <> 'quota_rejected'");
    });
  });

  describe("rule 4 — per-tier seeds, fill-if-absent", () => {
    it.each([
      ["free", 2, 1000],
      ["paid", 20, 100000],
      ["sponsor", 100, 1000000],
    ])("seeds the %s tier", (tier, rps, daily) => {
      expect(ddl).toContain(
        `jsonb_build_object('agent_key_rps', ${rps}, 'agent_key_daily_calls', ${daily}) || seats, updated_at = current_timestamp where license_type = '${tier}'`,
      );
    });

    it("keeps every canonical seats key in the column comment", () => {
      for (const key of [
        "max_tenants",
        "max_users_per_tenant",
        "max_projects",
        "max_versions",
        "max_ai_requests",
        "mock_rps",
        "mock_requests_per_month",
        "agent_invocation_retention_days",
        "agent_usage_rollup_retention_days",
        "agent_key_rps",
        "agent_key_daily_calls",
      ]) {
        expect(sql).toContain(key);
      }
    });
  });
});
