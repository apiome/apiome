/**
 * Structural assertions over the tenant document store migration (#7092, COA-5.15).
 *
 * V408 lets a tenant keep its document store objects in its own bucket. DB-free contract tests
 * pin its rules:
 *
 *   1. **One settings row per tenant**, gone with the tenant.
 *   2. **The credential is referenced, never copied**: no key or secret column.
 *   3. **`tenant` mode needs a credential and a bucket.**
 *   4. **An object can be recorded as held in a tenant bucket** (`tenant_s3`).
 *   5. **Owner and Admin get `document_store:manage`**; Editor and Viewer do not.
 *
 * These must stay in lock-step with apiome-rest's `app.tenant_document_store`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V408__tenant_document_stores_7092.sql";

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

describe("tenant document store migration (COA-5.15)", () => {
  it("is present in scripts/ and ordered after the rendered-document role migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V407__rendered_openapi_members_role_7089.sql"),
    );
  });

  it("keeps one settings row per tenant, removed with the tenant", () => {
    expect(ddl).toContain("create table if not exists apiome.tenant_document_stores");
    expect(ddl).toContain("tenant_id uuid primary key references apiome.tenants(id) on delete cascade");
  });

  it("references the sealed credential and never stores a key", () => {
    expect(ddl).toContain("references apiome.export_storage_credentials(id) on delete no action");
    expect(ddl).not.toMatch(/secret|access_key|password|token/);
  });

  it("requires a credential and a bucket for tenant mode", () => {
    expect(ddl).toContain("check (mode in ('platform', 'tenant'))");
    expect(ddl).toContain("check (mode <> 'tenant' or (credential_id is not null and bucket is not null))");
  });

  it("lets an object be recorded as held in a tenant bucket", () => {
    expect(ddl).toContain("check (backend in ('db', 's3', 'filesystem', 'tenant_s3'))");
  });

  it("adds the outage notification type", () => {
    expect(ddl).toContain("'document_store_unavailable'");
    expect(ddl).toContain("'seat_cap_blocked_sso'");
  });

  it("grants document_store:manage to Owner and Admin only", () => {
    expect(ddl).toContain("(v_owner, 'document_store', 'manage')");
    expect(ddl).toContain("(v_admin, 'document_store', 'manage')");
    expect(ddl).not.toContain("v_editor, 'document_store'");
    expect(ddl).not.toContain("v_viewer, 'document_store'");
    expect(ddl).toContain("perform apiome.seed_builtin_roles(t.id)");
  });
});
