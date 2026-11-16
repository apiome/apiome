/**
 * Structural assertions over the stored overlay chain migration (#5878, GVM-4.3).
 *
 * V385 stores an ordered chain of Overlay documents per revision and the publish render record.
 * DB-free contract tests pin its rules:
 *
 *   1. **Write-once rows**: an UPDATE trigger refuses every update; replacement is delete + insert.
 *   2. **One overlay per position per revision**, deferrable so positions compact in one transaction.
 *   3. **Known sources only**: manual, lint-fix, export-studio, enrichment-export.
 *   4. **The chain and its render go with the revision** (`ON DELETE CASCADE`).
 *
 * These must stay in lock-step with apiome-rest's `app.version_overlay_store` /
 * `app.version_overlay_chain`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V385__version_overlays_gvm_4_3.sql";

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

describe("stored overlay chain migration (GVM-4.3)", () => {
  it("is present in scripts/ and ordered after the usage controls migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V384__usage_controls_rdg_5_4.sql"));
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("cascades the chain and its render with the revision", () => {
    expect(ddl).toContain("version_record_id uuid not null references versions(id) on delete cascade");
    expect(ddl).toContain("version_record_id uuid primary key references versions(id) on delete cascade");
  });

  it("keeps one overlay per position, deferrably", () => {
    expect(ddl).toContain(
      "constraint version_overlays_position_uq unique (version_record_id, position) deferrable initially immediate",
    );
    expect(ddl).toContain("position integer not null check (position >= 0)");
  });

  it("accepts only the known sources", () => {
    expect(ddl).toContain(
      "check (source in ('manual', 'lint-fix', 'export-studio', 'enrichment-export'))",
    );
  });

  it("refuses every update", () => {
    expect(ddl).toContain("before update on version_overlays for each row execute function version_overlays_refuse_update()");
  });

  it("fingerprints the stored document and both rendered documents", () => {
    expect(ddl).toContain("content_fingerprint varchar(71) not null check (content_fingerprint like 'sha256:%')");
    expect(ddl).toContain("source_fingerprint varchar(71) not null");
    expect(ddl).toContain("resolved_fingerprint varchar(71) not null");
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.version_overlay_renders;");
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.version_overlays;");
  });
});
