/**
 * Structural assertions over the staged-import migration (#7192, DBP-1.9).
 *
 * V411 lets the UI import commit a version *staged* instead of holding a transaction open while
 * a person reviews it. DB-free contract tests pin its rules:
 *
 *   1. **The flag and the manifest are nullable columns with no default**, so the migration is a
 *      catalog-only change and every existing version reads as "not staged".
 *   2. **The sweeper's lookup is a partial index** over staged versions only.
 *
 * These must stay in lock-step with apiome-ui's `lib/db/import-staging.ts` and apiome-rest's
 * `Database._project_deleted_filter`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V411__import_pending_versions_7192.sql";

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

describe("staged import migration (DBP-1.9)", () => {
  it("is present in scripts/ and ordered after the usage counter migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V410__usage_tenant_day_7191.sql"));
  });

  it("adds the pending flag and the undo manifest to versions", () => {
    expect(ddl).toContain(
      "alter table apiome.versions add column if not exists import_pending_at timestamptz, add column if not exists import_pending jsonb;",
    );
  });

  it("adds them without a default or NOT NULL, so no row is rewritten", () => {
    const alter = ddl.slice(ddl.indexOf("alter table apiome.versions"), ddl.indexOf("create index"));
    expect(alter).not.toMatch(/default|not null/);
  });

  it("indexes only the staged versions for the sweeper", () => {
    expect(ddl).toContain(
      "create index if not exists idx_versions_import_pending on apiome.versions (import_pending_at) where import_pending_at is not null",
    );
  });

  it("can be applied twice", () => {
    expect(ddl).not.toMatch(/add column import_pending|create index idx_/);
  });
});
