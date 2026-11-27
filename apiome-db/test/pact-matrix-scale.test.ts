/**
 * Structural assertions over the matrix-scale migration (#6958, PFX-6.6).
 *
 * V452 lets the matrix read a pacticipant's newest publications in order instead of sorting all of
 * them. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first and comes after the pacticipant-owners migration.
 *   2. Both indexes lead with the pacticipant, then `created_at DESC, id` — the matrix's order.
 *   3. It changes no column or rule and drops nothing.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V452__pact_matrix_scale_6958.sql";

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

describe("matrix-scale migration (PFX-6.6)", () => {
  it("is present in scripts/ and ordered after the pacticipant-owners migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V451__pacticipant_owners_6956.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("orders a consumer's and a provider's publications newest first", () => {
    expect(ddl).toContain(
      "create index if not exists idx_pact_publication_consumer_recent on pact_publication (consumer_id, created_at desc, id)",
    );
    expect(ddl).toContain(
      "create index if not exists idx_pact_publication_provider_recent on pact_publication (provider_id, created_at desc, id)",
    );
  });

  it("changes no column or rule and drops nothing", () => {
    expect(ddl).not.toContain("alter table");
    expect(ddl).not.toContain("constraint");
    expect(ddl).not.toContain("drop ");
  });
});
