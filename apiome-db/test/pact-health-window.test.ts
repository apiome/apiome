/**
 * Structural assertions over the contract-health migration (#6955, PFX-6.3).
 *
 * V449 lets the **Health** page read a workspace's verification results inside a window without
 * scanning every workspace's results. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first.
 *   2. The window index leads with tenant_id, then created_at (the range the read filters on).
 *   3. It changes no column or rule of the table and drops nothing.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V449__pact_health_window_6955.sql";

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

describe("contract-health migration (PFX-6.3)", () => {
  it("is present in scripts/ and ordered after the verification-ops migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V444__pact_verification_ops_6949.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("builds the tenant window index", () => {
    expect(ddl).toContain(
      "create index if not exists idx_verification_result_tenant_window on verification_result (tenant_id, created_at)",
    );
  });

  it("changes no column or rule and drops nothing", () => {
    expect(ddl).not.toContain("alter table");
    expect(ddl).not.toContain("constraint");
    expect(ddl).not.toContain("drop ");
  });
});
