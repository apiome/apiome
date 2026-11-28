/**
 * Structural assertions over the migration-runs migration (#7313, PFX-8.16).
 *
 * V458 stores a broker migration the Migration wizard runs on the server:
 *
 *   1. It sets its own search path first and comes after the contract settings migration.
 *   2. A run belongs to a tenant and goes with it; its done keys go with the run.
 *   3. The source's credentials have no column: only the kind of sign-in is kept.
 *   4. A workspace has one running run at a time, and a run is finished exactly when it is not running.
 *   5. The new foreign keys are indexed.
 *
 * `apiome-rest/tests/test_pact_migration_run_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V458__pact_migration_runs_7313.sql";

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

describe("pact migration runs migration (PFX-8.16)", () => {
  it("is present in scripts/ and ordered after the contract settings migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V457__pact_contract_settings_7312.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("ties a run to its tenant and its done keys to the run", () => {
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(ddl).toContain("run_id uuid not null references pact_migration_run(id) on delete cascade");
    expect(ddl).toContain("primary key (run_id, source_key)");
  });

  it("has no column for the source's token or password", () => {
    // A column is `<name> <type>`; `auth_kind`'s values ('token', 'basic') are not columns.
    const columns = [...ddl.matchAll(/(?:\(|,) ([a-z_]+) (?:uuid|text|varchar|jsonb|integer|boolean|timestamp|bytea)/g)].map(
      (match) => match[1],
    );
    expect(columns).toContain("auth_kind");
    expect(columns.filter((name) => /token|password|secret|credential|authorization/.test(name))).toEqual([]);
    expect(ddl).toContain("check (auth_kind in ('token', 'basic', 'none'))");
  });

  it("allows one running run per tenant and finishes a run exactly when it stops running", () => {
    expect(ddl).toContain(
      "create unique index if not exists idx_pact_migration_run_one_running on pact_migration_run (tenant_id) " +
        "where status = 'running'",
    );
    expect(ddl).toContain("check (status in ('running', 'completed', 'stopped', 'failed'))");
    expect(ddl).toContain("check ((status = 'running') = (finished_at is null))");
    expect(ddl).toContain("check (mode in ('dry-run', 'copy'))");
  });

  it("indexes the new foreign keys", () => {
    expect(ddl).toContain("on pact_migration_run (tenant_id, created_at desc)");
    expect(ddl).toContain("on pact_migration_run (started_by) where started_by is not null");
  });
});
