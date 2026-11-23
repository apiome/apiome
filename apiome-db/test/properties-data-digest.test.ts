/**
 * Structural assertions over the project property digest migration (#7190, DBP-1.7).
 *
 * V409 lets a source apply find the project property with a given definition in the database
 * instead of loading the whole library. DB-free contract tests pin its rules:
 *
 *   1. **The digest is generated** from `data`, so no writer can leave it stale.
 *   2. **The lookup is indexed** by `(project_id, data_digest)`.
 *
 * These must stay in lock-step with apiome-rest's `app.source_apply_writer`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V409__properties_data_digest_7190.sql";

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

describe("project property digest migration (DBP-1.7)", () => {
  it("is present in scripts/ and ordered after the tenant document store migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V408__tenant_document_stores_7092.sql"),
    );
  });

  it("generates the digest from the property definition", () => {
    expect(ddl).toContain(
      "add column if not exists data_digest text generated always as (md5(data::text)) stored",
    );
  });

  it("indexes the lookup a source apply makes", () => {
    expect(ddl).toContain(
      "create index if not exists idx_properties_project_data_digest on apiome.properties (project_id, data_digest)",
    );
  });

  it("can be applied twice", () => {
    expect(ddl).not.toMatch(/add column data_digest|create index idx_/);
  });
});
