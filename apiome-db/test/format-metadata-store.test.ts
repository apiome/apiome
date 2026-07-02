/**
 * Structural assertions over the format-specific metadata store migration (#3757, MFI-7.2).
 *
 * V137 adds one open-ended JSONB column to `apiome.versions` — `format_metadata` — so each format
 * adapter can persist + read the identity it carries beyond the canonical model (Avro
 * subject/compatibility, gRPC package/edition, OData root, WSDL targetNamespace, registry
 * coordinates) without a schema change per format. It lives on `versions` (the universally-present
 * revision entity) rather than `api_artifacts` (only present after the normalizer runs), matching the
 * V136 (MFI-7.1) and V124 precedents.
 *
 * The suite is DB-free (this package asserts migration SQL structurally; end-to-end application is
 * proven against a live database elsewhere), so these tests pin the migration's contract: the column,
 * its type/nullability/default, the deliberate absence of an index, idempotency, additivity, and
 * documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V137__format_metadata_store_3757.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("format-metadata store migration", () => {
  it("is present in scripts/ and ordered after V136", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V136__source_format_protocol_columns_3756.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("alters the versions table (the universally-present catalog/revision entity)", () => {
    expect(lower).toMatch(/alter table apiome\.versions/);
  });

  it("adds format_metadata idempotently (ADD COLUMN IF NOT EXISTS)", () => {
    expect(lower).toMatch(/add column if not exists format_metadata\b/);
  });

  it("stores format_metadata as a non-null JSONB defaulting to an empty object (no per-format schema churn)", () => {
    expect(sql).toMatch(/format_metadata JSONB NOT NULL DEFAULT '\{\}'::jsonb/);
  });

  it("adds exactly one column to versions", () => {
    expect((lower.match(/add column if not exists/g) ?? []).length).toBe(1);
  });

  it("does not index format_metadata (provenance read per-revision, not a facet; avoids GIN write-amp)", () => {
    expect(lower).not.toMatch(/create index/);
  });

  it("uses uuid conventions free of gen_random_uuid (consistency, though no PK added)", () => {
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("documents the added column", () => {
    expect(sql).toMatch(/COMMENT ON COLUMN apiome\.versions\.format_metadata IS/);
    expect((sql.match(/COMMENT ON COLUMN apiome\.versions\./g) ?? []).length).toBe(1);
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
