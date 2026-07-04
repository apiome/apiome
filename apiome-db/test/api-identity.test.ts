/**
 * Structural assertions over the cross-format API identity migration (#4410, MFI-6.4).
 *
 * V140 adds `apiome.api_identity_groups` and `apiome.api_identity_members` so related catalog items
 * and publishable Projects can be grouped as representations of the same logical API. Each project
 * belongs to at most one group; membership records whether the link was manual or conversion-seeded.
 *
 * DB-free contract tests pin the migration shape, indexes, constraints, and additive rollback recipe.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V140__api_identity_4410.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("cross-format API identity migration", () => {
  it("is present in scripts/ and ordered after V139", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V139__conversion_provenance_4006.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the api_identity_groups table idempotently", () => {
    expect(lower).toMatch(/create table if not exists apiome\.api_identity_groups/);
  });

  it("creates the api_identity_members table idempotently", () => {
    expect(lower).toMatch(/create table if not exists apiome\.api_identity_members/);
  });

  it("scopes groups and members to tenants with cascade delete", () => {
    expect(lower).toMatch(
      /api_identity_groups[\s\S]*tenant_id\s+uuid\s+not null references apiome\.tenants\(id\) on delete cascade/,
    );
    expect(lower).toMatch(
      /api_identity_members[\s\S]*tenant_id\s+uuid\s+not null references apiome\.tenants\(id\) on delete cascade/,
    );
  });

  it("restricts each project to a single identity group per tenant", () => {
    expect(lower).toMatch(/unique\s*\(\s*tenant_id\s*,\s*project_id\s*\)/);
  });

  it("records link_source as manual or conversion", () => {
    expect(lower).toMatch(/link_source\s+varchar\(32\)\s+not null default 'manual'/);
    expect(lower).toMatch(/check\s*\(\s*link_source in\s*\(\s*'manual'\s*,\s*'conversion'\s*\)\s*\)/);
  });

  it("indexes groups by tenant and members by group and project", () => {
    expect(lower).toMatch(
      /create index if not exists idx_api_identity_groups_tenant\s+on apiome\.api_identity_groups\(tenant_id\)/,
    );
    expect(lower).toMatch(
      /create index if not exists idx_api_identity_members_group\s+on apiome\.api_identity_members\(tenant_id, group_id\)/,
    );
    expect(lower).toMatch(
      /create index if not exists idx_api_identity_members_project\s+on apiome\.api_identity_members\(tenant_id, project_id\)/,
    );
  });

  it("documents both tables", () => {
    expect(sql).toMatch(/COMMENT ON TABLE apiome\.api_identity_groups IS/);
    expect(sql).toMatch(/COMMENT ON TABLE apiome\.api_identity_members IS/);
  });
});
