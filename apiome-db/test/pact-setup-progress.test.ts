/**
 * Structural assertions over the Contracts set-up progress migration (#7317, PFX-8.20).
 *
 * V460 stores what a workspace marked and did on the **Set up contracts** page:
 *
 *   1. It sets its own search path first and comes after the migration sync migration.
 *   2. The row belongs to a tenant and goes with it.
 *   3. Only the page's sections can be marked, and only a known first-pact path chosen.
 *   4. The CI key is named whole (id and prefix together) and has no column for its secret.
 *   5. The new foreign key to `users` is indexed.
 *
 * `apiome-rest/tests/test_pact_setup_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V460__pact_setup_progress_7317.sql";

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

describe("pact set-up progress migration (PFX-8.20)", () => {
  it("is present in scripts/ and ordered after the migration sync migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V459__pact_migration_sync_7314.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("keys the row by its tenant and removes it with the tenant", () => {
    expect(ddl).toContain("tenant_id uuid primary key references tenants(id) on delete cascade");
  });

  it("lets only the page's six sections be marked", () => {
    expect(ddl).toContain(
      "check (marked <@ array['pacticipants', 'environments', 'pipelines', 'first-pact', 'provider', 'gates'])",
    );
  });

  it("lets only a known first-pact path be chosen", () => {
    expect(ddl).toContain("first_pact_path is null or first_pact_path in ('tests', 'spec')");
  });

  it("names the CI key whole and has no column for its secret", () => {
    expect(ddl).toContain("check ((ci_key_id is null) = (ci_key_prefix is null))");
    const columns = [...ddl.matchAll(/(?:\(|,) ([a-z_]+) (?:uuid|text|varchar|jsonb|integer|boolean|timestamp|bytea)/g)].map(
      (match) => match[1],
    );
    expect(columns.filter((name) => /secret|token|hash|cipher/.test(name))).toEqual([]);
  });

  it("keeps the per-repository record an object", () => {
    expect(ddl).toContain("check (jsonb_typeof(github) = 'object')");
  });

  it("indexes the foreign key to users", () => {
    expect(ddl).toContain(
      "create index if not exists idx_pact_setup_progress_updated_by on pact_setup_progress (updated_by) where updated_by is not null",
    );
  });
});
