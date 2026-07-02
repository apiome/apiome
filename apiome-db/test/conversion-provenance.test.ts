/**
 * Structural assertions over the convert-to-project provenance migration (#4006, MFI-22.5).
 *
 * V139 adds `apiome.conversion_provenance`, the append-only ledger that links each publishable OpenAPI
 * Project minted by the MFI-EPIC-22 convert flow back to the catalog item + revision it was converted
 * from — with the source format/protocol/tool provenance, the fidelity report the user reviewed, the
 * captured OpenAPI lint score, and the converter tool versions. The re-convert lookup (latest row per
 * source project) names the target Project a re-convert appends a new version to, so a changed source
 * produces a new version rather than a duplicate Project; a BEFORE UPDATE OR DELETE trigger keeps each
 * row immutable (a re-convert appends a new row).
 *
 * The suite is DB-free (this package asserts migration SQL structurally; end-to-end application is
 * proven against a live database elsewhere), so these tests pin the migration's contract: the table
 * and its source/target/fidelity/lint/tool columns, the two facet indexes, the write-once trigger +
 * guard function, idempotency, documentation, and that the migration is additive.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V139__conversion_provenance_4006.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("convert-to-project provenance migration", () => {
  it("is present in scripts/ and ordered after V138", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V138__catalog_item_publishable_guarantee_4010.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the conversion_provenance table idempotently (IF NOT EXISTS)", () => {
    expect(lower).toMatch(/create table if not exists apiome\.conversion_provenance/);
  });

  it("is tenant-scoped and cascades on tenant delete", () => {
    expect(lower).toMatch(/tenant_id\s+uuid\s+not null references apiome\.tenants\(id\) on delete cascade/);
  });

  it("records the source side: project, revision, format/protocol, version label, tool versions", () => {
    // The source project/revision may be deleted later; keep the row (SET NULL) so lineage survives.
    expect(lower).toMatch(/source_project_id\s+uuid\s+references apiome\.projects\(id\) on delete set null/);
    expect(lower).toMatch(/source_version_id\s+uuid\s+references apiome\.versions\(id\) on delete set null/);
    expect(lower).toMatch(/source_format\s+varchar\(128\)/);
    expect(lower).toMatch(/source_protocol\s+varchar\(64\)/);
    expect(lower).toMatch(/source_version_label\s+varchar\(255\)/);
    expect(lower).toMatch(/source_tool_versions\s+jsonb\s+not null default '\{\}'::jsonb/);
  });

  it("records the target side: the minted Project (NOT NULL, cascade) + its revision", () => {
    expect(lower).toMatch(/target_project_id\s+uuid\s+not null references apiome\.projects\(id\) on delete cascade/);
    expect(lower).toMatch(/target_version_id\s+uuid\s+references apiome\.versions\(id\) on delete set null/);
    expect(lower).toMatch(/target_version_label\s+varchar\(255\)/);
  });

  it("stores the fidelity report (JSONB) plus hoisted score/grade/tier columns", () => {
    expect(lower).toMatch(/fidelity_report\s+jsonb\s+not null default '\{\}'::jsonb/);
    expect(lower).toMatch(/fidelity_score\s+smallint/);
    expect(lower).toMatch(/fidelity_grade\s+varchar\(2\)/);
    expect(lower).toMatch(/fidelity_tier\s+varchar\(16\)/);
  });

  it("stores the captured OpenAPI lint score/grade and the converter tool versions", () => {
    expect(lower).toMatch(/lint_score\s+smallint/);
    expect(lower).toMatch(/lint_grade\s+varchar\(2\)/);
    expect(lower).toMatch(/converter_tool_versions\s+jsonb\s+not null default '\{\}'::jsonb/);
  });

  it("carries a reconverted flag and standard audit columns", () => {
    expect(lower).toMatch(/reconverted\s+boolean\s+not null default false/);
    expect(lower).toMatch(/created_by\s+uuid\s+references apiome\.users\(id\) on delete set null/);
    expect(lower).toMatch(/created_at\s+timestamptz\s+not null default current_timestamp/);
  });

  it("uses a gen_random_uuid primary key", () => {
    expect(lower).toMatch(/id\s+uuid\s+not null default gen_random_uuid\(\) primary key/);
  });

  it("indexes the re-convert lookup (tenant_id, source_project_id, created_at DESC), idempotently", () => {
    expect(lower).toMatch(
      /create index if not exists idx_conversion_provenance_source\s+on apiome\.conversion_provenance\(tenant_id, source_project_id, created_at desc\)/,
    );
    expect(
      (lower.match(/create index if not exists idx_conversion_provenance_source\b/g) ?? []).length,
    ).toBe(1);
  });

  it("indexes the reverse lookup (tenant_id, target_project_id, created_at DESC), idempotently", () => {
    expect(lower).toMatch(
      /create index if not exists idx_conversion_provenance_target\s+on apiome\.conversion_provenance\(tenant_id, target_project_id, created_at desc\)/,
    );
    expect(
      (lower.match(/create index if not exists idx_conversion_provenance_target\b/g) ?? []).length,
    ).toBe(1);
  });

  it("defines a guard function that rejects any mutation of a provenance row", () => {
    expect(lower).toMatch(/create or replace function conversion_provenance_forbid_mutation\(\)/);
    expect(lower).toMatch(/raise exception/);
    expect(lower).toMatch(/errcode = 'restrict_violation'/);
  });

  it("wires the guard as a BEFORE UPDATE OR DELETE FOR EACH ROW trigger, idempotently", () => {
    expect(lower).toMatch(
      /drop trigger if exists trigger_conversion_provenance_immutable on apiome\.conversion_provenance/,
    );
    expect(lower).toMatch(
      /create trigger trigger_conversion_provenance_immutable\s+before update or delete on apiome\.conversion_provenance\s+for each row\s+execute function conversion_provenance_forbid_mutation\(\)/,
    );
  });

  it("documents the table and the guard function", () => {
    expect(sql).toMatch(/COMMENT ON TABLE apiome\.conversion_provenance IS/);
    expect(sql).toMatch(/COMMENT ON FUNCTION conversion_provenance_forbid_mutation\(\) IS/);
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
