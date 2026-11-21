/**
 * Structural assertions over the frozen schema object migration (#7081, COA-5.5).
 *
 * V404 lets `version_spec_snapshots.content` be NULL: a frozen version's bytes move to a document
 * store object (`version_documents` role `frozen_schema`) and the row keeps the metadata. DB-free
 * contract tests pin its rules:
 *
 *   1. **Online** — the only DDL is a catalog-only `DROP NOT NULL`.
 *   2. **Nothing is lost** — no column or table is dropped, so rows written before the migration
 *      keep their bytes.
 *
 * The behaviour (freeze, serve, unfreeze) is exercised against Postgres in apiome-rest
 * `tests/test_rendered_documents_db.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V404__frozen_schema_object_7081.sql";

/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("frozen schema object migration (COA-5.5)", () => {
  it("is present in scripts/ and ordered after the document object tables", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V403__document_objects_content_stamp_7078.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("makes the snapshot content nullable", () => {
    expect(ddl).toContain(
      "alter table apiome.version_spec_snapshots alter column content drop not null;",
    );
  });

  it("drops nothing and rewrites no table", () => {
    expect(ddl).not.toMatch(/drop (table|column)/);
    expect(ddl).not.toMatch(/alter column [a-z_]+ (set data )?type/);
    expect(ddl).not.toContain("update apiome.");
  });
});
