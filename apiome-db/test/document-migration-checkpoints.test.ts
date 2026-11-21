/**
 * Structural assertions over the document migration checkpoint table (#7084, COA-5.8).
 *
 * V405 adds `apiome.document_migration_checkpoints`, where the apiome-rest migration job records
 * how far each step (copy, purge) got for each source, so an interrupted run resumes. DB-free
 * contract tests pin its rules:
 *
 *   1. **Online** — a new table only; nothing is dropped, altered or rewritten.
 *   2. **One row per (scope, step, source)** — the primary key the job upserts on.
 *   3. **Closed vocabularies** — the steps and sources the job knows.
 *
 * The behaviour (resume, re-run no-op) is exercised against Postgres in apiome-rest
 * `tests/test_document_migration_db.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V405__document_migration_checkpoints_7084.sql";

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

describe("document migration checkpoints (COA-5.8)", () => {
  it("is present in scripts/ and ordered after the frozen schema object migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V404__frozen_schema_object_7081.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("creates the checkpoint table keyed by scope, step and source", () => {
    expect(ddl).toContain("create table if not exists apiome.document_migration_checkpoints");
    expect(ddl).toContain("primary key (scope, step, source)");
    expect(ddl).toContain("completed_at timestamptz,");
  });

  it("limits steps and sources to the ones the job knows", () => {
    expect(ddl).toContain("check (step in ('copy', 'purge'))");
    expect(ddl).toContain(
      "check (source in ('adapter_source', 'import_snapshot', 'frozen_schema', 'export_artifact'))",
    );
  });

  it("drops nothing and rewrites no table", () => {
    expect(ddl).not.toMatch(/drop (table|column)/);
    expect(ddl).not.toMatch(/alter table/);
    expect(ddl).not.toContain("update apiome.");
  });
});
