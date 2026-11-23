/**
 * Structural assertions over the statement-level content-stamp triggers (DBP-1.19, #7202).
 *
 * V427 replaces the 35 row-level `trg_content_stamp` triggers of V403 with statement-level
 * triggers over transition tables. DB-free contract tests pin the rules; behaviour (bumps once per
 * statement and per transaction, ignored columns, moved rows, rollback of a savepoint) and the
 * 5 % overhead budget were checked against PostgreSQL in apiome-rest
 * `tests/test_content_stamp_db.py` and in the PR description.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V427__content_stamp_statement_triggers_7202.sql";

let sql = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — whitespace collapsed. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .replace(/' '/g, "") // adjacent string literals: 'a ' 'b' -> 'a b'
    .toLowerCase();
});

describe("content-stamp statement triggers (DBP-1.19)", () => {
  it("follows the sweep migration in order", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBe(files.indexOf("V426__indexed_sweep_due_selection_7201.sql") + 1);
  });

  it("creates one statement-level trigger per event with the matching transition table", () => {
    expect(ddl).toContain(
      "create trigger trg_content_stamp_insert after insert on apiome.%i referencing new table as new_rows for each statement",
    );
    expect(ddl).toContain(
      "create trigger trg_content_stamp_update after update on apiome.%i referencing old table as old_rows new table as new_rows for each statement",
    );
    expect(ddl).toContain(
      "create trigger trg_content_stamp_delete after delete on apiome.%i referencing old table as old_rows for each statement",
    );
    expect(ddl).not.toContain("for each row execute function apiome.bump_version_content_stamp(%l)");
  });

  it("drops the row-level trigger of every table it re-creates", () => {
    expect(ddl).toContain("drop trigger if exists trg_content_stamp on apiome.%i");
  });

  it("keeps the revision row trigger and the one trigger function", () => {
    expect(ddl).not.toContain("create trigger trg_content_stamp before update on apiome.versions");
    const functions = ddl.match(/create or replace function apiome\.[a-z_]+\(/g) ?? [];
    expect(functions.filter((f) => f.includes("bump_"))).toEqual([
      "create or replace function apiome.bump_version_content_stamp(",
    ]);
  });

  it("no longer serializes rows to jsonb in the statement path", () => {
    const start = ddl.indexOf("create or replace function apiome.bump_version_content_stamp(");
    const body = ddl.slice(start, ddl.indexOf("$fn$;", start));
    // The only to_jsonb left is the versions row trigger's own comparison.
    expect(body.match(/to_jsonb/g)?.length).toBe(2);
    expect(body).toContain("tg_level = 'row'");
    expect(ddl).not.toContain("$1->>");
  });

  it("claims many revisions at once with exact matching", () => {
    expect(ddl).toContain("create or replace function apiome.claim_versions(p_setting text, p_ids uuid[])");
    expect(ddl).toContain("not (i::text = any (v_seen))");
    expect(ddl).toMatch(/set_config\(p_setting, v_marks \|\| array_to_string\(v_new, ','\) \|\| ',', true\)/);
    expect(ddl).toContain("claim_versions('apiome.content_stamp_bumped', v_ids)");
    expect(ddl).toContain("claim_versions('apiome.publish_counts_cleared', v_ids)");
  });

  it("bumps all claimed revisions with one UPDATE and still clears the publish counts", () => {
    expect(ddl).toContain("update apiome.versions set content_stamp = content_stamp + 1 where id = any (v_claimed)");
    expect(ddl).toContain("update apiome.versions set operation_count = null, schema_count = null");
    expect(ddl).toContain("tg_table_name in ('classes', 'version_path', 'path_operation')");
  });

  it("keeps the ignored-columns rule and the bookkeeping list of the versions row", () => {
    expect(ddl).toContain("array['updated_at', 'canvas_metadata']");
    for (const column of ["content_stamp", "lint_error_count", "sunset_at", "operation_count", "schema_count"]) {
      expect(ddl).toContain(`'${column}'`);
    }
  });

  it("covers the same 35 tables as V403", async () => {
    const v403 = (await fs.readFile(path.join(SCRIPTS_DIR, "V403__document_objects_content_stamp_7078.sql"), "utf8"))
      .replace(/\s+/g, " ");
    const tables = (s: string) => new Set([...s.matchAll(/ARRAY\['([a-z_]+)',/g)].map((m) => m[1]));
    const before = tables(v403.slice(v403.indexOf("v_triggers CONSTANT")));
    const after = tables(sql.replace(/\s+/g, " ").slice(sql.replace(/\s+/g, " ").indexOf("v_triggers CONSTANT")));
    expect(before.size).toBe(35);
    expect(after).toEqual(before);
  });

  it("documents its rollback", () => {
    expect(sql).toContain("Rollback notes");
    expect(sql).toContain("DROP FUNCTION IF EXISTS apiome.claim_versions(text, uuid[]);");
    expect(sql).toContain("DROP FUNCTION IF EXISTS apiome.content_stamp_row_filters(regclass);");
  });
});
