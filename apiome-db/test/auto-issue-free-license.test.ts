/**
 * Structural assertions over the Free-license auto-issue migration (#4212, OLO-5.2).
 *
 * V183 makes the V182 `tenant_licenses` row exist without user action:
 *   - `apiome.attach_free_license(uuid)` — the single service function; idempotent
 *     (`ON CONFLICT (tenant_id) DO NOTHING`) so an already-licensed tenant is never downgraded,
 *   - an AFTER INSERT trigger on `apiome.tenants` so *every* create path attaches Free in the
 *     same transaction as the tenant insert,
 *   - a backfill so no pre-existing tenant is stranded when enforcement (OLO-5.3) lands.
 *
 * These are DB-free contract tests pinning that shape so a later edit cannot silently drop the
 * "every tenant holds a license from birth" guarantee that OLO-5.3's 403s depend on.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V183__auto_issue_free_license_4212.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("auto-issue Free license migration", () => {
  it("is present and ordered after the V182 attachment model it populates", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V182__tenant_licenses_4211.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("defines the single service function attach_free_license(uuid)", () => {
    expect(lower).toMatch(
      /create or replace function apiome\.attach_free_license\(p_tenant_id uuid\)/,
    );
  });

  it("selects the Free plan from the V097 catalog by name and type", () => {
    expect(lower).toMatch(/name = 'free' and license_type = 'free'/);
  });

  it("is idempotent — an already-licensed tenant is never downgraded or duplicated", () => {
    expect(lower).toMatch(/on conflict \(tenant_id\) do nothing/);
  });

  it("warns instead of aborting tenant creation when the Free plan is missing", () => {
    expect(lower).toContain("raise warning");
    expect(lower).toContain("return null");
  });

  it("records auto-issue provenance in the notes column", () => {
    expect(lower).toContain("auto-issued free on tenant creation");
  });

  it("fires for every tenant-create path via AFTER INSERT trigger, same transaction", () => {
    expect(lower).toMatch(
      /create trigger trigger_tenants_attach_free_license\s+after insert on apiome\.tenants\s+for each row\s+execute function apiome\.tenants_attach_free_license\(\)/,
    );
  });

  it("recreates the trigger idempotently (DROP TRIGGER IF EXISTS first)", () => {
    expect(lower).toMatch(
      /drop trigger if exists trigger_tenants_attach_free_license on apiome\.tenants/,
    );
  });

  it("backfills every pre-existing tenant without a license row", () => {
    expect(lower).toMatch(/insert into apiome\.tenant_licenses \(tenant_id, license_id, notes\)/);
    expect(lower).toMatch(
      /not exists \(\s*select 1 from apiome\.tenant_licenses tl where tl\.tenant_id = t\.id\s*\)/,
    );
    expect(lower).toContain("backfilled free for pre-existing tenant");
  });

  it("backfill has no enabled/deleted_at filter — disabled tenants are licensed too", () => {
    // A restored or re-enabled tenant must not surface as unlicensed under OLO-5.3.
    expect(lower).not.toContain("deleted_at is null");
    expect(lower).not.toContain("enabled is true");
  });

  it("documents both functions", () => {
    expect(lower).toContain("comment on function apiome.attach_free_license(uuid)");
    expect(lower).toContain("comment on function apiome.tenants_attach_free_license()");
  });

  it("every function/trigger DDL is guarded (CREATE OR REPLACE / DROP IF EXISTS)", () => {
    const functions = (lower.match(/create (or replace )?function/g) || []).length;
    const guardedFunctions = (lower.match(/create or replace function/g) || []).length;
    expect(guardedFunctions).toBe(functions);
    const triggers = (lower.match(/create trigger/g) || []).length;
    const drops = (lower.match(/drop trigger if exists/g) || []).length;
    expect(drops).toBe(triggers);
  });
});
