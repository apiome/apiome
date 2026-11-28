/**
 * Structural assertions over the migration keep-in-sync migration (#7314, PFX-8.17).
 *
 * V459 lets a finished migration be copied again on a schedule:
 *
 *   1. It sets its own search path first and comes after the migration-runs migration.
 *   2. A sync belongs to its run and its tenant, and goes with either.
 *   3. The source's credentials are kept sealed exactly while the sync is on.
 *   4. A workspace keeps one migration in sync at a time; the interval is bounded.
 *   5. The new foreign keys and the sweep's read are indexed.
 *
 * `apiome-rest/tests/test_pact_migration_sync_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V459__pact_migration_sync_7314.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("pact migration keep-in-sync migration (PFX-8.17)", () => {
  it("is present in scripts/ and ordered after the migration-runs migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V458__pact_migration_runs_7313.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("ties a sync to its run and its tenant", () => {
    expect(ddl).toContain("run_id uuid primary key references pact_migration_run(id) on delete cascade");
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
  });

  it("keeps the credentials sealed, and only while the sync is on", () => {
    expect(ddl).toContain("credential_ciphertext bytea");
    expect(ddl).not.toMatch(/\b(token|password)\s+(text|varchar)/);
    expect(ddl).toContain("check (enabled = (credential_ciphertext is not null))");
    expect(ddl).toContain("check ((credential_ciphertext is null) = (key_version is null))");
  });

  it("keeps one migration in sync per tenant, every 5 minutes to a day", () => {
    expect(ddl).toContain(
      "create unique index if not exists idx_pact_migration_sync_one_enabled on pact_migration_sync (tenant_id) where enabled",
    );
    expect(ddl).toContain("check (interval_seconds between 300 and 86400)");
  });

  it("indexes the new foreign keys and the sweep's read", () => {
    expect(ddl).toContain("on pact_migration_sync (tenant_id);");
    expect(ddl).toContain("on pact_migration_sync (enabled_by) where enabled_by is not null");
    expect(ddl).toContain("on pact_migration_sync (next_run_at) where enabled");
  });
});
