/**
 * Structural assertions over the source-format & protocol columns migration (#3756, MFI-7.1).
 *
 * V136 adds three nullable/default-empty columns to `apiome.versions` — `source_format`, `protocol`,
 * and `source_tool_versions` — plus partial facet indexes, so browse/search (MFI-EPIC-6) and the
 * catalog projection can say what *kind* of API every revision is. Unlike `api_artifacts`
 * (canonical-model persistence, only present after the normalizer runs), `versions` exists for every
 * import, which is why the facet columns live here (V124 quality-score precedent).
 *
 * The suite is DB-free (this package asserts migration SQL structurally; end-to-end application is
 * proven against a live database elsewhere), so these tests pin the migration's contract: the columns,
 * their types/nullability, the facet indexes, idempotency, and full column documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V136__source_format_protocol_columns_3756.sql";

/** The three columns this migration adds to apiome.versions. */
const COLUMNS = ["source_format", "protocol", "source_tool_versions"] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("source-format & protocol columns migration", () => {
  it("is present in scripts/ and ordered after V135", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V135__canonical_api_model_persistence_3739.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("alters the versions table (the universally-present catalog/revision entity)", () => {
    expect(lower).toMatch(/alter table apiome\.versions/);
  });

  it("adds all three columns idempotently (ADD COLUMN IF NOT EXISTS)", () => {
    for (const col of COLUMNS) {
      expect(lower).toMatch(new RegExp(`add column if not exists ${col}\\b`));
    }
  });

  it("types source_format/protocol as the api_artifacts-matching varchars", () => {
    // Same widths as api_artifacts.format (128) / api_artifacts.protocol (64) so the vocabularies line up.
    expect(sql).toMatch(/source_format VARCHAR\(128\)/);
    expect(sql).toMatch(/protocol VARCHAR\(64\)/);
  });

  it("leaves source_format and protocol nullable (sparse until backfill MFI-7.3)", () => {
    // Neither facet column may be NOT NULL — existing/non-import revisions have no format yet.
    expect(sql).not.toMatch(/source_format VARCHAR\(128\)[^,]*NOT NULL/i);
    expect(sql).not.toMatch(/\bprotocol VARCHAR\(64\)[^,]*NOT NULL/i);
  });

  it("stores source_tool_versions as a non-null JSONB defaulting to an empty object", () => {
    expect(sql).toMatch(/source_tool_versions JSONB NOT NULL DEFAULT '\{\}'::jsonb/);
  });

  it("indexes both facet dimensions with partial live, non-null indexes (AC: indexed for facets)", () => {
    expect(lower).toMatch(
      /create index if not exists idx_versions_source_format\s+on apiome\.versions\(source_format\)\s+where deleted_at is null and source_format is not null/,
    );
    expect(lower).toMatch(
      /create index if not exists idx_versions_protocol\s+on apiome\.versions\(protocol\)\s+where deleted_at is null and protocol is not null/,
    );
  });

  it("creates the facet indexes idempotently (IF NOT EXISTS)", () => {
    const idempotent = (lower.match(/create index if not exists idx_versions_(source_format|protocol)\b/g) ?? []).length;
    expect(idempotent).toBe(2);
  });

  it("does not index source_tool_versions (it is provenance, not a facet)", () => {
    expect(lower).not.toMatch(/create index[^;]*source_tool_versions/);
  });

  it("uses uuid conventions free of gen_random_uuid (consistency, though no PK added)", () => {
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("documents every added column", () => {
    for (const col of COLUMNS) {
      expect(sql).toMatch(new RegExp(`COMMENT ON COLUMN apiome\\.versions\\.${col} IS`));
    }
    expect((sql.match(/COMMENT ON COLUMN apiome\.versions\./g) ?? []).length).toBe(COLUMNS.length);
  });

  it("is purely additive — no destructive DROP/DELETE/TRUNCATE in the applied body", () => {
    // The rollback recipe lives in a leading comment block; the executable statements must not drop.
    const executable = sql
      .split("\n")
      .filter((line) => !line.trimStart().startsWith("--"))
      .join("\n")
      .toLowerCase();
    expect(executable).not.toMatch(/\bdrop\s+(table|column|index)\b/);
    expect(executable).not.toMatch(/\b(delete\s+from|truncate)\b/);
  });
});
