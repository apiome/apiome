/**
 * Structural assertions over the document object tables and revision content stamp migration
 * (#7078, COA-5.2).
 *
 * V403 adds `document_objects`, `version_documents` and `versions.content_stamp`, bumped by one
 * trigger function on every normalized table of a revision. DB-free contract tests pin its rules:
 *
 *   1. **Online** — the stamp column has a constant default (catalog-only, no rewrite of
 *      `versions`) and nothing alters an existing column's type.
 *   2. **One trigger function** — every `trg_content_stamp` trigger runs
 *      `bump_version_content_stamp`, and the normalized tables the issue names are all covered.
 *   3. **Once per transaction** — the bump is guarded by a transaction-local mark.
 *   4. **Document metadata identity** — one object per (tenant, SHA-256); version documents carry
 *      a closed role list and rendered provenance.
 *
 * The behaviour itself (bumps, reads, coverage of every referencing table) is exercised against
 * Postgres in apiome-rest `tests/test_content_stamp_db.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V403__document_objects_content_stamp_7078.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("document objects and content stamp migration (COA-5.2)", () => {
  it("is present in scripts/ and ordered after the document store blob table", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V402__document_store_blob_7077.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("adds the stamp with a constant default, so versions is not rewritten", () => {
    expect(ddl).toContain(
      "alter table apiome.versions add column if not exists content_stamp bigint not null default 0;",
    );
    expect(ddl).not.toMatch(/alter column [a-z_]+ (set data )?type/);
  });

  it("keeps one document object per tenant and digest", () => {
    expect(ddl).toContain("unique (tenant_id, sha256)");
    expect(ddl).toContain("check (sha256 ~ '^[0-9a-f]{64}$')");
    expect(ddl).toContain("check (backend in ('db', 's3', 'filesystem'))");
  });

  it("limits version document roles and requires rendered provenance", () => {
    expect(ddl).toContain(
      "check (role in ('original', 'original_part', 'rendered_openapi', 'rendered_canonical', 'frozen_schema'))",
    );
    expect(ddl).toContain("check ((role = 'original_part') = (part_path is not null))");
    expect(ddl).toContain(
      "unique nulls not distinct (version_id, role, part_path, content_stamp, generator, generator_version)",
    );
  });

  it("bumps once per transaction through a transaction-local mark", () => {
    expect(ddl).toContain("set_config('apiome.content_stamp_bumped'");
    expect(ddl).toMatch(/set_config\('apiome\.content_stamp_bumped', [^;]*, true\)/);
  });

  it("uses one trigger function for every content stamp trigger", () => {
    const functions = ddl.match(/create or replace function apiome\.[a-z_]+\(/g) ?? [];
    expect(functions.filter((f) => f.includes("bump_"))).toEqual([
      "create or replace function apiome.bump_version_content_stamp(",
    ]);
    const executes = ddl.match(/execute function apiome\.[a-z_]+\(/g) ?? [];
    expect(new Set(executes)).toEqual(
      new Set(["execute function apiome.bump_version_content_stamp("]),
    );
  });

  it("covers every normalized table the issue names", () => {
    for (const table of [
      "classes",
      "class_properties",
      "properties",
      "version_path",
      "path_operation",
      "path_parameter",
      "path_response",
      "version_server",
      "version_security_scheme",
      "version_component_pins",
    ]) {
      expect(ddl).toContain(`array['${table}',`);
    }
    expect(ddl).toContain("before update on apiome.versions");
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP FUNCTION IF EXISTS apiome.bump_version_content_stamp();");
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.version_documents;");
    expect(sql).toContain("ALTER TABLE apiome.versions DROP COLUMN IF EXISTS content_stamp;");
  });
});
