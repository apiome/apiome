/**
 * Structural assertions over the API products migration (APX-1.1, #6098).
 *
 * V387 adds `api_products` and `api_product_members`, and widens the graph by the `api_product`
 * node kind and the `includes` edge kind. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V387__api_products_apx_1_1.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("API products migration (APX-1.1)", () => {
  it("is present in scripts/ and ordered after V386", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V386__probe_consents_asp_4_1.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("keeps product slugs handle-shaped and unique among live products", () => {
    expect(lower).toContain("create table if not exists api_products (");
    expect(lower).toContain("check (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$')");
    expect(lower).toMatch(/idx_api_products_tenant_slug\s+on api_products \(tenant_id, slug\)\s+where deleted_at is null/);
  });

  it("bounds visibility and state, and leaves a product unowned when its team goes", () => {
    expect(lower).toContain("check (visibility in ('private', 'workspace', 'portal'))");
    expect(lower).toContain("check (state in ('draft', 'published', 'deprecated', 'retired'))");
    expect(lower).toContain("owner_team_id uuid references teams(id) on delete set null");
  });

  it("keeps members in their product's tenant and lists each once", () => {
    expect(lower).toContain("create table if not exists api_product_members (");
    expect(lower).toContain("check (member_kind in ('project_version', 'project_latest', 'mcp_server', 'catalog_item'))");
    expect(lower).toMatch(
      /foreign key \(product_id, tenant_id\) references api_products \(id, tenant_id\) on delete cascade/,
    );
    expect(lower).toMatch(
      /api_product_members_identity_key unique nulls not distinct\s+\(product_id, member_kind, member_ref, version_selector, environment\)/,
    );
  });

  it("gives a version selector to project_version members only", () => {
    expect(lower).toContain("check ((member_kind = 'project_version') = (version_selector is not null))");
  });

  it("adds api_product to the graph's node kinds and includes to its edge kinds", () => {
    expect(lower).toMatch(/from_kind in \([^)]*'api_product'\)/);
    expect(lower).toMatch(/to_kind in \([^)]*'api_product'\)/);
    expect(lower).toMatch(/catalog_edges_kind_check\s+check \(edge_kind in \([^)]*'includes'\)\)/);
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("apx-1.1 (#6098)");
  });
});
