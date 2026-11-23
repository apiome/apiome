/**
 * Structural assertions over the DBP-1.15 (#7198) migrations:
 *
 *   - V422 stores the lint error count and the sunset date of a revision as generated columns,
 *     indexes the two filters Home and the sunset timeline run, and re-creates the V403
 *     content-stamp trigger function with both columns in its non-content list (in a BEFORE
 *     trigger NEW does not carry recomputed generated values, so without that every bookkeeping
 *     UPDATE would bump versions.content_stamp).
 *   - V423 adds the per-revision count rollup Home's counters read.
 *
 * Behaviour (no spurious stamp bump, the clamp, the NULL for a malformed report) was checked on a
 * migrated scale database; these tests keep the definitions from drifting.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const COLUMNS = "V422__versions_lint_error_count_sunset_at_7198.sql";
const COUNTS = "V423__version_content_counts_7198.sql";
const STAMP = "V403__document_objects_content_stamp_7078.sql";

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

describe("DBP-1.15 migrations", () => {
  it("follow the DBP-1.12 migrations in order", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf("V421__usage_primary_keys_7195.sql");
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(COLUMNS)).toBe(previous + 1);
    expect(files.indexOf(COUNTS)).toBe(previous + 2);
  });
});

describe("generated lint and sunset columns (V422)", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(COLUMNS);
  });

  it("guards the lint count cast, so a malformed report cannot fail a write", () => {
    expect(code).toContain("add column if not exists lint_error_count integer generated always as");
    expect(code).toContain("when jsonb_typeof(quality_report->'severity_counts'->'error') = 'number'");
    expect(code).toMatch(/least\( greatest\( ?trunc\(\(quality_report->'severity_counts'->>'error'\)::numeric\), 0\), 2147483647 \)::integer/);
  });

  it("reads the three sunset spellings in revision_deprecation's order", () => {
    expect(code).toContain("add column if not exists sunset_at text generated always as");
    const order = ["'sunsetat'", "'sunsetdate'", "'sunset_date'"].map((key) => code.indexOf(`metadata->>${key}`));
    expect(order.every((at) => at > -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  it("stores both columns rather than computing them on read", () => {
    expect(code.match(/\) stored/g)).toHaveLength(2);
  });

  it("indexes the attention and sunset filters as partial indexes", () => {
    expect(code).toContain(
      "create index if not exists idx_versions_lint_attention on apiome.versions (project_id) " +
        "where deleted_at is null and published = false and lint_error_count > 0",
    );
    expect(code).toContain(
      "create index if not exists idx_versions_sunset_at on apiome.versions (project_id, sunset_at) " +
        "where deleted_at is null and sunset_at is not null",
    );
  });

  it("re-creates the content-stamp trigger with only the two new columns added", async () => {
    const replaced = stampFunction(code);
    const original = stampFunction(await codeOf(STAMP));
    expect(replaced).toContain("'lint_error_count', 'sunset_at'];");
    expect(replaced.replace(", 'lint_error_count', 'sunset_at'", "")).toBe(original);
  });
});

describe("per-revision count rollup (V423)", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(COUNTS);
  });

  it("keys one row per revision and goes with it", () => {
    expect(code).toContain(
      "version_id uuid primary key references apiome.versions (id) on delete cascade",
    );
  });

  it("records the content stamp the counts were taken at", () => {
    expect(code).toContain("content_stamp bigint not null check (content_stamp >= 0)");
    expect(code).toContain("class_count integer not null check (class_count >= 0)");
    expect(code).toContain("class_property_count integer not null check (class_property_count >= 0)");
    expect(code).toContain("max_class_created_at timestamptz");
  });
});
