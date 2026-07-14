/**
 * Structural assertions over the tenant MCP policy data model migration (#4766, MTG-1.2).
 *
 * V161 adds `apiome.tenant_mcp_policies` and `apiome.tenant_mcp_policy_tools`, plus the
 * idempotent `seed_tenant_mcp_policy(tenant)` function for tenant-create seeding.
 * Existing-tenant backfill is deferred to MTG-1.5 (#4769).
 *
 * DB-free contract tests pin the migration shape: tables, FKs, uniqueness, the
 * ceiling vs default enable-set split, default_mode check, and seed (no backfill loop).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V161__tenant_mcp_policies_4766.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("tenant MCP policy data model migration", () => {
  it("is present in scripts/ and ordered after V160", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V160__version_quality_report_captured_at_import.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates both tables idempotently", () => {
    expect(lower).toMatch(/create table if not exists tenant_mcp_policies/);
    expect(lower).toMatch(/create table if not exists tenant_mcp_policy_tools/);
  });

  it("documents rollback drops for up/down clean", () => {
    expect(lower).toContain("drop function if exists apiome.seed_tenant_mcp_policy(uuid)");
    expect(lower).toContain("drop table if exists apiome.tenant_mcp_policy_tools");
    expect(lower).toContain("drop table if exists apiome.tenant_mcp_policies");
  });

  describe("tenant_mcp_policies", () => {
    it("is one row per tenant with cascade delete", () => {
      expect(lower).toMatch(
        /tenant_id\s+uuid primary key references tenants\(id\) on delete cascade/,
      );
    });

    it("constrains default_mode to all | inherit_registry | explicit, defaulting to all", () => {
      expect(lower).toMatch(/default 'all'/);
      expect(lower).toMatch(
        /tenant_mcp_policies_default_mode_ck[\s\S]*?check \(default_mode in \('all', 'inherit_registry', 'explicit'\)\)/,
      );
    });

    it("tracks updated_by against users with SET NULL on delete", () => {
      expect(lower).toMatch(
        /updated_by\s+uuid references users\(id\) on delete set null/,
      );
    });
  });

  describe("tenant_mcp_policy_tools", () => {
    it("is tenant-scoped with cascade delete", () => {
      expect(lower).toMatch(
        /tenant_mcp_policy_tools[\s\S]*?tenant_id\s+uuid not null references tenants\(id\) on delete cascade/,
      );
    });

    it("keeps tool ids unique per tenant via primary key", () => {
      expect(lower).toMatch(
        /tenant_mcp_policy_tools_pk primary key \(tenant_id, tool_id\)/,
      );
    });

    it("splits ceiling vs default enable-set with defaults ⊆ ceiling", () => {
      expect(lower).toMatch(/in_ceiling\s+boolean not null default true/);
      expect(lower).toMatch(/default_enabled\s+boolean not null default true/);
      expect(lower).toMatch(
        /tenant_mcp_policy_tools_default_subseteq_ceiling_ck[\s\S]*?check \(not default_enabled or in_ceiling\)/,
      );
    });

    it("rejects empty tool_id values", () => {
      expect(lower).toMatch(
        /tenant_mcp_policy_tools_tool_id_nonempty[\s\S]*?check \(char_length\(trim\(tool_id\)\) > 0\)/,
      );
    });
  });

  describe("ceiling vs default enable-set comments", () => {
    it("documents ceiling membership on in_ceiling", () => {
      expect(lower).toMatch(/comment on column tenant_mcp_policy_tools\.in_ceiling is/);
      expect(lower).toContain("ceiling");
      expect(sql).toMatch(/max tools any key/i);
    });

    it("documents default enable-set on default_enabled", () => {
      expect(lower).toMatch(
        /comment on column tenant_mcp_policy_tools\.default_enabled is/,
      );
      expect(sql).toMatch(/default enable-set/i);
      expect(sql).toMatch(/inherit/i);
    });
  });

  describe("seed_tenant_mcp_policy", () => {
    it("defines the idempotent per-tenant seed function", () => {
      expect(lower).toMatch(
        /create or replace function apiome\.seed_tenant_mcp_policy\(p_tenant uuid\)/,
      );
      expect(lower).toMatch(
        /insert into apiome\.tenant_mcp_policies \(tenant_id, default_mode\)/,
      );
      expect(lower).toMatch(/on conflict \(tenant_id\) do nothing/);
      expect(lower).toContain("'all'");
    });

    it("does not backfill existing tenants (deferred to MTG-1.5)", () => {
      expect(lower).not.toMatch(/for t in select id from apiome\.tenants loop/);
      expect(lower).not.toMatch(/perform apiome\.seed_tenant_mcp_policy\(t\.id\)/);
    });
  });
});
