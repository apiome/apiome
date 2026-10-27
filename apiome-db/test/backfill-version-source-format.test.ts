/**
 * Structural assertions over the source-format / protocol backfill (#3758, MFI-7.3).
 *
 * V332 tags every revision that predates V136's `versions.source_format` / `versions.protocol`
 * columns, so the browse protocol/format facets (MFI-6.1) include them: the canonical artifact's
 * format and paradigm when one exists, `arazzo` / `rest` for a repository file classed as Arazzo,
 * and `openapi` / `rest` for everything else. Values follow the vocabulary the live import path
 * writes (`protocol` is the canonical paradigm — Arazzo is `rest`).
 *
 * The suite is DB-free (this package asserts migration SQL structurally); it pins the contract that
 * matters for a data migration: what it writes, that it only fills gaps, that it leaves
 * `updated_at` alone, and that it is safe to re-run.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V332__backfill_version_source_format_protocol_3758.sql";

/** The migration's executable SQL, lower-cased, with `--` comment lines removed. */
let executable = "";
/** The full migration text, comments included. */
let sql = "";

/**
 * Split the executable SQL into its UPDATE statements, in file order.
 *
 * @returns One string per `UPDATE … ;` statement.
 */
function updateStatements(): string[] {
  return executable
    .split(";")
    .map((statement) => statement.trim())
    .filter((statement) => statement.startsWith("update"));
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  executable = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("source-format / protocol backfill migration", () => {
  it("is present in scripts/ and ordered after the columns it fills (V136)", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V136__source_format_protocol_columns_3756.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(executable).toContain("set search_path to apiome, public");
  });

  it("is data-only: no DDL, deletes or truncates", () => {
    expect(executable).not.toMatch(/\b(create|alter|drop)\s+(table|column|index)\b/);
    expect(executable).not.toMatch(/\b(delete\s+from|truncate)\b/);
  });

  it("runs four ordered UPDATEs on apiome.versions", () => {
    const updates = updateStatements();
    expect(updates).toHaveLength(4);
    for (const update of updates) {
      expect(update).toMatch(/^update apiome\.versions v\b/);
    }
  });

  it("step 1 takes format and paradigm from the canonical artifact, live row first", () => {
    const [step1] = updateStatements();
    expect(step1).toContain("from apiome.api_artifacts art");
    expect(step1).toMatch(/distinct on \(art\.version_id\)/);
    expect(step1).toMatch(/order by art\.version_id, \(art\.deleted_at is null\) desc, art\.created_at desc/);
    expect(step1).toContain("coalesce(nullif(trim(v.source_format), ''), a.format)");
    expect(step1).toContain("coalesce(nullif(trim(v.protocol), ''), a.paradigm)");
  });

  it("step 2 tags Arazzo repository imports as arazzo / rest with V223's detection", () => {
    const step2 = updateStatements()[1];
    expect(step2).toContain("set source_format = 'arazzo'");
    expect(step2).toContain("coalesce(nullif(trim(v.protocol), ''), 'rest')");
    expect(step2).toContain("from apiome.tenant_repository_imports tri");
    expect(step2).toContain("trf.detected_kind ilike 'arazzo%'");
    expect(step2).toContain("s.source_kind = 'arazzo'");
  });

  it("step 3 tags every remaining revision openapi / rest", () => {
    const step3 = updateStatements()[2];
    expect(step3).toContain("set source_format = 'openapi'");
    expect(step3).toContain("coalesce(nullif(trim(v.protocol), ''), 'rest')");
    expect(step3).toMatch(/where nullif\(trim\(v\.source_format\), ''\) is null$/);
  });

  it("step 4 gives OpenAPI / Swagger / Arazzo revisions without a protocol rest", () => {
    const step4 = updateStatements()[3];
    expect(step4).toContain("set protocol = 'rest'");
    expect(step4).toMatch(/where nullif\(trim\(v\.protocol\), ''\) is null/);
    expect(step4).toContain("like 'openapi-%'");
    expect(step4).toContain("like 'swagger-%'");
  });

  it("never writes a protocol outside the browse facet vocabulary", () => {
    // `workflow` is not an ApiParadigm value: the protocol facet could never select it.
    expect(executable).not.toContain("'workflow'");
    const written = [
      ...executable.matchAll(/(?:protocol = |nullif\(trim\(v\.protocol\), ''\), )'([a-z_]+)'/g),
    ].map((match) => match[1]);
    expect(written).toHaveLength(3);
    expect(new Set(written)).toEqual(new Set(["rest"]));
  });

  it("only fills NULL or blank values (every step is guarded)", () => {
    for (const update of updateStatements()) {
      expect(update).toMatch(/nullif\(trim\(v\.(source_format|protocol)\), ''\) is null/);
    }
  });

  it("does not touch updated_at (a backfill is not an edit; V157's NOTIFY trigger stays quiet)", () => {
    expect(executable).not.toContain("updated_at");
  });

  it("documents its sources, safety and rollback in the header", () => {
    expect(sql).toMatch(/#3758/);
    expect(sql).toMatch(/Rollback notes:/);
    expect(sql).toMatch(/Idempotent/);
  });
});
