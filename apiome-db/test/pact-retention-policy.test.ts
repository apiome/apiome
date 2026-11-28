/**
 * Structural assertions over the Contracts clean-up policy migration (#7311, PFX-8.14).
 *
 * V456 stores a workspace's clean-up rules, its nightly switch and its restore window, and indexes
 * the Recently deleted list. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first and comes after the environment history migration.
 *   2. Deployed and released versions cannot be turned off: no column says so.
 *   3. Every number is bounded, and the other-branch age needs its count.
 *   4. The row goes with its tenant, and the new foreign key is indexed.
 *   5. Both Recently deleted reads have a partial index over the deleted rows only.
 *
 * `apiome-rest/tests/test_pact_retention_policy_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V456__pact_retention_policy_7311.sql";

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

describe("pact retention policy migration (PFX-8.14)", () => {
  it("is present in scripts/ and ordered after the environment history migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V455__pact_environment_history_7310.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("is one row per tenant, removed with the tenant", () => {
    expect(ddl).toContain("create table if not exists pact_retention_policy");
    expect(ddl).toContain("tenant_id uuid primary key references tenants(id) on delete cascade");
  });

  it("has no switch for keeping deployed or released versions", () => {
    expect(ddl).not.toMatch(/deployed|released/);
  });

  it("bounds every number", () => {
    expect(ddl).toContain("check (keep_main_branch_latest is null or keep_main_branch_latest between 1 and 1000)");
    expect(ddl).toContain("check (keep_other_branch_latest is null or keep_other_branch_latest between 1 and 1000)");
    expect(ddl).toContain(
      "check (keep_other_branch_days is null or (keep_other_branch_latest is not null and keep_other_branch_days between 1 and 3650))",
    );
    expect(ddl).toContain("check (restore_window_days between 1 and 365)");
    expect(ddl).toContain("check (cardinality(keep_tags) <= 50 and array_position(keep_tags, null) is null)");
  });

  it("starts with clean-up off and a 30-day restore window", () => {
    expect(ddl).toContain("nightly_enabled boolean not null default false");
    expect(ddl).toContain("restore_window_days integer not null default 30");
  });

  it("indexes the new foreign key", () => {
    expect(ddl).toContain("on pact_retention_policy (updated_by) where updated_by is not null");
  });

  it("indexes both Recently deleted reads over the deleted rows only", () => {
    expect(ddl).toContain("on pacticipant (tenant_id, deleted_at desc) where deleted_at is not null");
    expect(ddl).toContain(
      "on pacticipant_version (pacticipant_id, deleted_at desc) where deleted_at is not null and delete_cause <> 'pacticipant'",
    );
  });
});
