/**
 * Structural assertions over the catalog-item / non-publishable-guarantee migration (#4010, MFI-23.1).
 *
 * V138 draws the Project-vs-Catalog boundary at the data layer. It adds a single `publishable`
 * BOOLEAN to `apiome.projects` — `true` (the DEFAULT, so every pre-existing project is unaffected) for
 * publishable Projects, `false` for non-publishable catalog items — plus a partial composite facet
 * index backing both list surfaces, and a BEFORE UPDATE trigger that makes the flag write-once so a
 * catalog item can never be promoted to a publishable Project by a stray UPDATE (the "no publish"
 * rule lives in the database, not just the UI).
 *
 * The suite is DB-free (this package asserts migration SQL structurally; end-to-end application is
 * proven against a live database elsewhere), so these tests pin the migration's contract: the
 * column, its type/nullability/default, the facet index, the immutability trigger + guard function,
 * idempotency, documentation, and that the migration is additive (no destructive table/column/index
 * drops or data deletion).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V138__catalog_item_publishable_guarantee_4010.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("catalog-item / non-publishable-guarantee migration", () => {
  it("is present in scripts/ and ordered after V137", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V137__format_metadata_store_3757.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("alters the projects table (the Project-vs-Catalog boundary lives on projects)", () => {
    expect(lower).toMatch(/alter table apiome\.projects/);
  });

  it("adds the publishable column idempotently (ADD COLUMN IF NOT EXISTS)", () => {
    expect(lower).toMatch(/add column if not exists publishable\b/);
  });

  it("types publishable as a NOT NULL boolean defaulting to true (existing projects unaffected)", () => {
    // DEFAULT true is load-bearing: every pre-existing project stays publishable; only non-OpenAPI
    // imports opt into publishable=false.
    expect(sql).toMatch(/publishable BOOLEAN NOT NULL DEFAULT true/);
  });

  it("documents the publishable column", () => {
    expect(sql).toMatch(/COMMENT ON COLUMN apiome\.projects\.publishable IS/);
  });

  it("backs both list surfaces with a partial composite (tenant_id, publishable) live index", () => {
    expect(lower).toMatch(
      /create index if not exists idx_projects_tenant_publishable\s+on apiome\.projects\(tenant_id, publishable\)\s+where deleted_at is null/,
    );
  });

  it("creates the facet index idempotently (IF NOT EXISTS)", () => {
    expect((lower.match(/create index if not exists idx_projects_tenant_publishable\b/g) ?? []).length).toBe(1);
  });

  it("defines a guard function that rejects a changed publishable flag", () => {
    expect(lower).toMatch(/create or replace function projects_forbid_publishable_change\(\)/);
    // The guard must compare new vs old with NULL-safe IS DISTINCT FROM and raise on a change.
    expect(lower).toMatch(/new\.publishable is distinct from old\.publishable/);
    expect(lower).toMatch(/raise exception/);
    expect(lower).toMatch(/errcode = 'restrict_violation'/);
  });

  it("wires the guard as a BEFORE UPDATE FOR EACH ROW trigger on projects, idempotently", () => {
    expect(lower).toMatch(/drop trigger if exists trigger_projects_publishable_immutable on apiome\.projects/);
    expect(lower).toMatch(
      /create trigger trigger_projects_publishable_immutable\s+before update on apiome\.projects\s+for each row\s+execute function projects_forbid_publishable_change\(\)/,
    );
  });

  it("documents the guard function", () => {
    expect(sql).toMatch(/COMMENT ON FUNCTION projects_forbid_publishable_change\(\) IS/);
  });

  it("uses uuid conventions free of gen_random_uuid (consistency, though no PK added)", () => {
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("is purely additive — no destructive table/column/index drop or data deletion in the body", () => {
    // The rollback recipe lives in a leading comment block; the executable statements must not drop
    // tables/columns/indexes or delete data. (DROP TRIGGER/FUNCTION are the idempotent re-create
    // pattern and are intentionally allowed.)
    const executable = sql
      .split("\n")
      .filter((line) => !line.trimStart().startsWith("--"))
      .join("\n")
      .toLowerCase();
    expect(executable).not.toMatch(/\bdrop\s+(table|column|index)\b/);
    expect(executable).not.toMatch(/\b(delete\s+from|truncate)\b/);
  });
});
