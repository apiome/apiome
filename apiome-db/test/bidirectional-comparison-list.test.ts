/**
 * Structural assertions over the comparison-list index migration (#6929, PFX-2.5).
 *
 * V440 adds the one index the **Pact comparisons** list needs
 * (`apiome-rest/src/app/verification_result_store.py`, `list_bidirectional_results`):
 * `(tenant_id, seq DESC)` over the bi-directional rows only. It is idempotent and touches nothing
 * but that index.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V440__bidirectional_comparison_list_6929.sql";

/** Comments removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("bi-directional comparison list index (PFX-2.5)", () => {
  it("is ordered after the bi-directional verification migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V439__bidirectional_verification_6927.sql"));
  });

  it("sets its own search_path", () => {
    expect(ddl.startsWith("set search_path to apiome, public;")).toBe(true);
  });

  it("creates exactly the partial (tenant_id, seq desc) index, idempotently", () => {
    expect(ddl).toContain(
      "create index if not exists idx_verification_result_tenant_bidirectional on verification_result (tenant_id, seq desc) where kind = 'bidirectional';",
    );
    const statements = ddl.split(";").map((statement) => statement.trim()).filter(Boolean);
    expect(statements).toHaveLength(2);
  });
});
