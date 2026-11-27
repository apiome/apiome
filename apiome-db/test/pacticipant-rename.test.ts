/**
 * Structural assertions over the pacticipant rename migration (#7307, PFX-8.10).
 *
 * V454 adds `pacticipant.display_name` and `pacticipant_alias`, the names a pacticipant has had.
 * DB-free contract tests pin it:
 *
 *   1. It sets its own search path first and comes after the standing-sources migration.
 *   2. The display name is optional and never blank.
 *   3. An alias hangs off its pacticipant by the composite `(id, tenant_id)` key and goes with it.
 *   4. An alias has the handle's shape, and every reference is indexed.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V454__pacticipant_rename_7307.sql";

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

describe("pacticipant rename migration (PFX-8.10)", () => {
  it("is present in scripts/ and ordered after the standing-sources migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V453__provider_contract_sources_7304.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("adds an optional display name that is never blank", () => {
    expect(ddl).toContain("add column if not exists display_name varchar(255)");
    expect(ddl).toContain("check (display_name is null or btrim(display_name) <> '')");
  });

  it("keeps aliases with their pacticipant, inside its workspace", () => {
    expect(ddl).toContain("constraint pacticipant_alias_pkey primary key (pacticipant_id, tenant_id, slug)");
    expect(ddl).toContain(
      "foreign key (pacticipant_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
  });

  it("gives an alias the handle's shape", () => {
    expect(ddl).toContain("check (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$')");
  });

  it("indexes the lookup and every reference", () => {
    expect(ddl).toContain("on pacticipant_alias (tenant_id, slug)");
    expect(ddl).toContain("on pacticipant_alias (created_by) where created_by is not null");
  });
});
