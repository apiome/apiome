/**
 * Structural assertions over the DBP-1.16 (#7199) migration, V424:
 *
 *   - versions.operation_count / schema_count, recorded by a trigger when a revision is published
 *     and cleared when it is unpublished or when a class, path or operation row is written;
 *   - the V403 / V422 content-stamp trigger function re-created with both columns in its
 *     non-content list (so recording, clearing and the backfill do not bump content_stamp) and
 *     with the clearing added for the three counted tables only;
 *   - the trigram indexes the Browse search palette's name matching uses.
 *
 * Behaviour (counts recorded at publish, cleared by a class write but not by a class_schema
 * write, no content_stamp bump from the backfill, every index chosen by its query) was checked on
 * a migrated scale database; these tests keep the definitions from drifting.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V424__public_browse_counts_and_name_search_7199.sql";
const PREVIOUS_STAMP = "V422__versions_lint_error_count_sunset_at_7198.sql";

/** A migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** The `bump_version_content_stamp` function definition in a migration. */
function stampFunction(code: string): string {
  const start = code.indexOf("create or replace function apiome.bump_version_content_stamp()");
  const end = code.indexOf("$fn$;", start);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  return code.slice(start, end);
}

describe("V424: public browse counts and name search", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows the DBP-1.15 migrations in order", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf("V423__version_content_counts_7198.sql");
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  describe("stored counts", () => {
    it("adds two nullable, non-negative integer columns without rewriting versions", () => {
      expect(code).toContain(
        "add column if not exists operation_count integer constraint versions_operation_count_check check (operation_count >= 0)",
      );
      expect(code).toContain(
        "add column if not exists schema_count integer constraint versions_schema_count_check check (schema_count >= 0)",
      );
      // No DEFAULT and not generated: a catalog-only change, and NULL means "not recorded".
      expect(code).not.toMatch(/operation_count integer[^,;]*(default|generated)/);
      expect(code).not.toMatch(/schema_count integer[^,;]*(default|generated)/);
    });

    it("records the counts when a revision is published and clears them when it is unpublished", () => {
      const start = code.indexOf("create or replace function apiome.set_version_publish_counts()");
      const fn = code.slice(start, code.indexOf("$fn$;", start));
      expect(fn).toContain("if not new.published then new.operation_count := null; new.schema_count := null;");
      // Published now, or published again while a count is missing.
      expect(fn).toContain("elsif not old.published or new.operation_count is null or new.schema_count is null then");
      // The same two counts the Browse card fallback computes.
      expect(fn).toContain(
        "from apiome.version_path vp join apiome.path_operation po on po.version_path_id = vp.id where vp.version_id = new.id",
      );
      expect(fn).toContain("from apiome.classes c where c.version_id = new.id and c.deleted_at is null");
    });

    it("fires only for statements that set published, before the row is written", () => {
      expect(code).toContain(
        "create trigger trg_versions_publish_counts before update of published on apiome.versions for each row execute function apiome.set_version_publish_counts()",
      );
      // Re-runnable.
      expect(code).toContain("drop trigger if exists trg_versions_publish_counts on apiome.versions");
    });

    it("backfills published live revisions once, and only rows that lack a count", () => {
      const start = code.indexOf("update apiome.versions v set operation_count = coalesce(o.operation_count, 0)");
      expect(start).toBeGreaterThan(-1);
      const backfill = code.slice(start, code.indexOf(";", start));
      expect(backfill).toContain("schema_count = coalesce(s.schema_count, 0)");
      expect(backfill).toContain("and pv.published and pv.deleted_at is null");
      expect(backfill).toContain("and (v.operation_count is null or v.schema_count is null)");
      // The backfill runs after the stamp function ignores the two columns.
      expect(start).toBeGreaterThan(code.indexOf("create or replace function apiome.bump_version_content_stamp()"));
    });
  });

  describe("content-stamp trigger function", () => {
    it("treats the two counts as non-content, with everything V422 already ignored", () => {
      const fn = stampFunction(code);
      for (const column of [
        "content_stamp",
        "updated_at",
        "mcp_public_doc_tsv",
        "mcp_public_embedding",
        "quality_score",
        "quality_grade",
        "quality_report",
        "quality_report_fingerprint",
        "lint_error_count",
        "sunset_at",
        "operation_count",
        "schema_count",
      ]) {
        expect(fn, column).toContain(`'${column}'`);
      }
    });

    it("clears the counts for class, path and operation writes only, once per revision and transaction", () => {
      const fn = stampFunction(code);
      expect(fn).toContain("v_counted constant boolean := tg_table_name in ('classes', 'version_path', 'path_operation');");
      const clear =
        "if v_counted and apiome.claim_version_publish_counts_clear(v_version) then " +
        "update apiome.versions set operation_count = null, schema_count = null " +
        "where id = v_version and (operation_count is not null or schema_count is not null); end if;";
      // Both resolver branches (a version_id column, a resolver query) clear.
      expect(fn.split(clear).length - 1).toBe(2);
      // Its own transaction-local mark, so a stamp already bumped by another table does not hide it.
      expect(code).toContain("current_setting('apiome.publish_counts_cleared', true)");
      expect(code).toContain("set_config('apiome.publish_counts_cleared', v_marks || p_version_id::text || ',', true)");
    });

    it("is otherwise V422's function", async () => {
      const normalize = (fn: string) =>
        fn
          .replace(/, 'operation_count', 'schema_count'\]/, "]")
          .replace(/v_counted constant boolean := [^;]*; /, "")
          .replaceAll(
            "if v_counted and apiome.claim_version_publish_counts_clear(v_version) then " +
              "update apiome.versions set operation_count = null, schema_count = null " +
              "where id = v_version and (operation_count is not null or schema_count is not null); end if; ",
            "",
          );
      expect(normalize(stampFunction(code))).toBe(stampFunction(await codeOf(PREVIOUS_STAMP)));
    });
  });

  describe("trigram indexes", () => {
    it("indexes the name expressions the suggestion statement matches", () => {
      for (const definition of [
        "create index if not exists idx_projects_name_slug_trgm on apiome.projects using gin ((name || ' ' || slug) gin_trgm_ops) where deleted_at is null",
        "create index if not exists idx_classes_name_trgm on apiome.classes using gin (name gin_trgm_ops) where deleted_at is null",
        "create index if not exists idx_class_properties_name_trgm on apiome.class_properties using gin (name gin_trgm_ops)",
        "create index if not exists idx_version_path_pathname_trgm on apiome.version_path using gin (pathname gin_trgm_ops)",
        "create index if not exists idx_path_operation_description_name_trgm on apiome.path_operation_description using gin ((coalesce(summary, '') || ' ' || coalesce(operation_id, '')) gin_trgm_ops)",
      ]) {
        expect(code).toContain(definition);
      }
    });

    it("adds exactly those five, each re-runnable", () => {
      const created = code.match(/create index[^;]*;/g) ?? [];
      expect(created).toHaveLength(5);
      for (const statement of created) expect(statement).toContain("create index if not exists");
    });
  });
});
