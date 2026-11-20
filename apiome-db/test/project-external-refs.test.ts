/**
 * Structural assertions over the project external `$ref` migration (#7051, COA-2.8).
 *
 * V398 keeps, per project and URL, the last refresh, the last fetched snapshot, an optional pin and
 * the last detected change. DB-free contract tests pin its rules:
 *
 *   1. **One row per project and URL** — a refresh upserts it.
 *   2. **Known statuses only**: ok, changed, unreachable, blocked.
 *   3. **A pin is all-or-nothing** — digest and document together.
 *   4. **The rows go with the project** (`ON DELETE CASCADE`).
 *
 * These must stay in lock-step with apiome-rest's `app.project_external_ref_store`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V398__project_external_refs_7051.sql";

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

describe("project external $ref migration (COA-2.8)", () => {
  it("is present in scripts/ and ordered after the OpenAPI 3.2 constructs migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V397__openapi_32_project_constructs_7048.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("keeps one row per project and URL", () => {
    expect(ddl).toContain("constraint project_external_refs_url_uq unique (project_id, url)");
  });

  it("accepts only the known statuses", () => {
    expect(ddl).toContain("check (status in ('ok', 'changed', 'unreachable', 'blocked'))");
  });

  it("sets a pin's digest and document together", () => {
    expect(ddl).toContain("check ((pinned_digest is null) = (pinned_document is null))");
  });

  it("goes with the project and the tenant", () => {
    expect(ddl).toContain("project_id uuid not null references projects(id) on delete cascade");
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
  });

  it("documents its rollback", () => {
    expect(sql).toContain("DROP TABLE IF EXISTS apiome.project_external_refs;");
  });
});
