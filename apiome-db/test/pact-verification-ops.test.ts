/**
 * Structural assertions over the verification operations migration (#6949, PFX-5.5).
 *
 * V444 gives every verification result its trigger, its run duration and the evidence run that
 * holds its log, and indexes a provider's history. DB-free contract tests pin its rules:
 *
 *   1. **Closed list**: `trigger` is NULL (recorded before V444) or one of the five triggers.
 *   2. **A duration is never negative.**
 *   3. **The evidence run is not a foreign key**: a result outlives a pruned evidence run.
 *
 * These must stay in lock-step with apiome-rest's `app.verification_result.TRIGGERS`;
 * `apiome-rest/tests/test_pact_verification_ops_db.py` proves the same rules against a migrated
 * database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V444__pact_verification_ops_6949.sql";

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

describe("verification operations migration (PFX-5.5)", () => {
  it("is present in scripts/ and ordered after the results and bi-directional kinds", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V434__pact_verification_result_6917.sql"));
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V439__bidirectional_verification_6927.sql"));
  });

  it("sets its own search path before altering anything", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBe(ddl.indexOf("set search_path"));
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("alter table"));
  });

  it("adds nullable columns idempotently", () => {
    expect(ddl).toContain("add column if not exists trigger varchar(16),");
    expect(ddl).toContain("add column if not exists duration_ms integer,");
    expect(ddl).toContain("add column if not exists evidence_run_id uuid;");
  });

  it("keeps the trigger to the closed list", () => {
    expect(ddl).toContain(
      "trigger is null or trigger in ('published', 'hosted', 'manual', 'stale-recheck', 'bidirectional')",
    );
  });

  it("never stores a negative duration", () => {
    expect(ddl).toContain("check (duration_ms is null or duration_ms >= 0)");
  });

  it("does not reference the evidence ledger", () => {
    expect(ddl).not.toContain("references apiome.verification_run");
    expect(ddl).not.toContain("foreign key (evidence_run_id");
  });

  it("indexes a provider's history newest first", () => {
    expect(ddl).toContain(
      "create index if not exists idx_verification_result_provider_history on verification_result (tenant_id, provider_id, seq desc)",
    );
  });
});
