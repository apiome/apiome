/**
 * Structural assertions over the usage tenant-day counter migration (#7191, DBP-1.8).
 *
 * V410 lets the usage ingest read a tenant's admitted events for the day with one primary-key
 * probe instead of summing the ledger under the tenant lock. DB-free contract tests pin its rules:
 *
 *   1. **One row per tenant and UTC day**, keyed by `(tenant_id, day)`, gone with the tenant.
 *   2. **The count can never go negative.**
 *   3. **The backfill sums the ledger** for today and yesterday only, and is safe to run twice.
 *
 * These must stay in lock-step with apiome-rest's `app.usage_ingest_store`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V410__usage_tenant_day_7191.sql";

/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("usage tenant-day counter migration (DBP-1.8)", () => {
  it("is present in scripts/ and ordered after the property digest migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V409__properties_data_digest_7190.sql"),
    );
  });

  it("keys one counter per tenant and day, cascading with the tenant", () => {
    expect(ddl).toContain("create table if not exists usage_tenant_day");
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(ddl).toContain("constraint usage_tenant_day_pkey primary key (tenant_id, day)");
  });

  it("refuses a negative count", () => {
    expect(ddl).toContain("check (events_used >= 0)");
  });

  it("backfills today and yesterday from the ledger, once", () => {
    expect(ddl).toContain("sum(b.received - b.rejected)");
    expect(ddl).toContain("b.received_day >= (current_timestamp at time zone 'utc')::date - 1");
    expect(ddl).toContain("on conflict (tenant_id, day) do nothing");
  });
});
