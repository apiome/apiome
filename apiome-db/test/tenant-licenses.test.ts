/**
 * Structural assertions over the tenant-license attachment migration (#4211, OLO-5.1).
 *
 * V182 introduces `apiome.tenant_licenses`, the single row recording which V097 catalog license a
 * tenant holds:
 *   - UNIQUE tenant_id → at most one active license per tenant,
 *   - license_id FK to `apiome.licenses` with ON DELETE RESTRICT (a held plan cannot vanish),
 *   - issued_at / issued_by / notes provenance columns.
 *
 * These are DB-free contract tests pinning that shape so a later edit cannot silently regress the
 * "one active license per tenant" guarantee EPIC-5 (auto-issue, enforcement, REST surface) builds on.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V182__tenant_licenses_4211.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("tenant-licenses migration", () => {
  it("is present and ordered after V181", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V181__provider_identity_uniqueness_4187.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the tenant_licenses table idempotently", () => {
    expect(lower).toMatch(/create table if not exists\s+tenant_licenses/);
  });

  it("enforces at most one active license per tenant (UNIQUE tenant_id)", () => {
    expect(lower).toMatch(
      /constraint\s+uq_tenant_licenses_tenant_id\s+unique\s*\(tenant_id\)/,
    );
  });

  it("attaches tenants to the V097 catalog, cascading with the tenant", () => {
    expect(lower).toMatch(
      /tenant_id\s+uuid\s+not null references apiome\.tenants\(id\)\s+on delete cascade/,
    );
  });

  it("refuses to delete a catalog plan that tenants still hold (RESTRICT)", () => {
    expect(lower).toMatch(
      /license_id\s+uuid\s+not null references apiome\.licenses\(id\)\s+on delete restrict/,
    );
  });

  it("records provenance: issued_at, issued_by (nullable, SET NULL), notes", () => {
    expect(lower).toMatch(/issued_at\s+timestamptz\s+not null default current_timestamp/);
    expect(lower).toMatch(
      /issued_by\s+uuid\s+references apiome\.users\(id\) on delete set null/,
    );
    expect(lower).toMatch(/notes\s+text/);
  });

  it("indexes the reverse lookups (license_id, issued_by) idempotently", () => {
    expect(lower).toMatch(
      /create index if not exists idx_tenant_licenses_license_id/,
    );
    expect(lower).toMatch(
      /create index if not exists idx_tenant_licenses_issued_by/,
    );
  });

  it("documents the entitlement/license split on the table comment", () => {
    // user entitlement = how many tenants you may create; tenant license = what each tenant may do
    expect(lower).toContain("comment on table apiome.tenant_licenses");
    expect(lower).toContain("user entitlement");
    expect(lower).toContain("user_entitlements");
  });

  it("is idempotent — table and index DDL are all guarded with IF NOT EXISTS", () => {
    const creates = (lower.match(/create (table|index)/g) || []).length;
    const guarded = (lower.match(/create (table|index) if not exists/g) || []).length;
    expect(guarded).toBe(creates);
  });
});
