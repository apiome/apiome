/**
 * Structural assertions over the members' OpenAPI document role (#7089, COA-5.13).
 *
 * V407 lets `apiome.version_documents` hold a second rendered OpenAPI document per revision, role
 * `rendered_openapi_members` (what a workspace member reads: OpenAPI 3.2, private operations
 * kept), beside the public `rendered_openapi`. DB-free contract tests pin its rules:
 *
 *   1. **Online** — constraints only, each added `NOT VALID` and validated separately.
 *   2. **The role list grows** — every earlier role is still allowed.
 *   3. **Rendered provenance covers the new role** — stamp, generator and generator version.
 *
 * The behaviour (a members' document is cached and not purged as a stale public one) is exercised
 * against Postgres in apiome-rest `tests/test_rendered_documents_db.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V407__rendered_openapi_members_role_7089.sql";

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

describe("members' OpenAPI document role (COA-5.13)", () => {
  it("is present in scripts/ and ordered after the document lifecycle migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V406__document_object_lifecycle_7086.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("changes constraints only", () => {
    expect(ddl).not.toMatch(/create table|drop table|add column|drop column|alter column/);
  });

  it("adds each constraint not valid and validates it in its own statement", () => {
    for (const name of ["version_documents_role_check", "version_documents_rendered_provenance"]) {
      expect(ddl).toContain(`drop constraint if exists ${name};`);
      expect(ddl).toMatch(new RegExp(`add constraint ${name} check \\([^;]*\\) not valid;`));
      expect(ddl).toContain(`validate constraint ${name};`);
    }
  });

  it("keeps every earlier role and adds the members' one", () => {
    expect(ddl).toContain(
      "check (role in ('original', 'original_part', 'rendered_openapi', 'rendered_openapi_members', 'rendered_canonical', 'frozen_schema'))",
    );
  });

  it("requires provenance on the members' document too", () => {
    expect(ddl).toContain(
      "check (role not in ('rendered_openapi', 'rendered_openapi_members', 'rendered_canonical') or (content_stamp is not null and generator is not null and generator_version is not null))",
    );
  });
});
