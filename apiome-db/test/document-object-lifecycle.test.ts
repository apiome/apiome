/**
 * Structural assertions over the document object lifecycle migration (#7086, COA-5.10).
 *
 * V406 keeps `document_objects.ref_count` equal to the object's live references and adds the
 * lifecycle audit. DB-free contract tests pin its rules:
 *
 *   1. **A live reference** is a `version_documents` link whose revision and tenant are not
 *      deleted; a soft-deleted project still counts (it can be restored).
 *   2. **Every change recounts**: link insert, re-point (update) and delete, revision delete or
 *      restore, tenant delete or restore.
 *   3. **Zero is stamped** (`unreferenced_at`) so apiome-rest's job can wait out a grace period.
 *   4. **The audit** names a closed set of events, and each deleted tenant is purged once.
 *
 * These must stay in lock-step with apiome-rest's `app.document_lifecycle` and the
 * `*_document_object*` methods of `app.database.Database`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V406__document_object_lifecycle_7086.sql";

let ddl = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
});

describe("document object lifecycle migration (COA-5.10)", () => {
  it("is present in scripts/ and ordered after the migration checkpoints", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V405__document_migration_checkpoints_7084.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(ddl).toContain("set search_path to apiome, public;");
  });

  it("adds the zero stamp and the integrity flag as nullable columns", () => {
    expect(ddl).toContain("add column if not exists unreferenced_at timestamptz,");
    expect(ddl).toContain("add column if not exists integrity_failed_at timestamptz;");
  });

  it("counts only links of live revisions in live tenants", () => {
    expect(ddl).toContain("create or replace function apiome.recount_document_objects(object_ids uuid[])");
    expect(ddl).toContain("and v.deleted_at is null and t.deleted_at is null");
    expect(ddl).not.toContain("p.deleted_at is null");
  });

  it("stamps unreferenced_at at zero and clears it when a reference returns", () => {
    expect(ddl).toContain("when live.n = 0 then coalesce(o.unreferenced_at, now()) else null");
  });

  it("recounts on link insert, re-point and delete", () => {
    expect(ddl).toContain("after insert on apiome.version_documents referencing new table as new_rows");
    expect(ddl).toContain(
      "after update on apiome.version_documents referencing old table as old_rows new table as new_rows",
    );
    expect(ddl).toContain("after delete on apiome.version_documents referencing old table as old_rows");
  });

  it("recounts when a revision or a tenant is deleted or restored", () => {
    expect(ddl).toContain("after update of deleted_at on apiome.versions for each row");
    expect(ddl).toContain("after update of deleted_at on apiome.tenants for each row");
    expect(ddl).toContain("where o.tenant_id = new.id::text");
  });

  it("audits a closed set of lifecycle events", () => {
    expect(ddl).toContain("create table if not exists apiome.document_lifecycle_events");
    expect(ddl).toContain(
      "check (event in ('object_purged', 'object_purge_failed', 'tenant_purged', 'integrity_failed', 'rendered_dropped'))",
    );
  });

  it("purges each deleted tenant once", () => {
    expect(ddl).toContain("create table if not exists apiome.document_tenant_purges ( tenant_id uuid primary key");
  });

  it("backfills every existing object and drops nothing", () => {
    expect(ddl).toContain("select apiome.recount_document_objects(array(select id from apiome.document_objects));");
    expect(ddl).not.toMatch(/drop (table|column|function)/);
  });
});
