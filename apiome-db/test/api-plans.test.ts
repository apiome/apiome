/**
 * Structural assertions over the API plans migration (APX-1.2, #6099).
 *
 * V388 adds `api_plans`: tiers of an API product with an auth strategy, declared limits, an approval
 * mode, the gateway configs they are provisioned to and their terms. DB-free contract tests pin the
 * shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V388__api_plans_apx_1_2.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("API plans migration (APX-1.2)", () => {
  it("is present in scripts/ and ordered after V387", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V387__api_products_apx_1_1.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("keeps plan slugs handle-shaped and unique among a product's live plans", () => {
    expect(lower).toContain("create table if not exists api_plans (");
    expect(lower).toContain("check (slug ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$')");
    expect(lower).toMatch(/idx_api_plans_product_slug\s+on api_plans \(product_id, slug\)\s+where deleted_at is null/);
  });

  it("keeps a plan in its product's tenant", () => {
    expect(lower).toMatch(
      /foreign key \(product_id, tenant_id\) references api_products \(id, tenant_id\) on delete cascade/,
    );
  });

  it("bounds the auth strategy, approval and state", () => {
    expect(lower).toContain("check (auth_strategy in ('key_auth', 'oauth2_client_credentials', 'mtls', 'none'))");
    expect(lower).toContain("check (approval in ('auto', 'manual'))");
    expect(lower).toContain("check (state in ('draft', 'published', 'deprecated', 'retired'))");
  });

  it("shapes the limits, auth config, counts and terms URL", () => {
    expect(lower).toContain("check (jsonb_typeof(limits) = 'array')");
    expect(lower).toContain("check (jsonb_typeof(auth_config) = 'object')");
    expect(lower).toContain("check (concurrency is null or concurrency > 0)");
    expect(lower).toContain("check (credential_ttl_days is null or credential_ttl_days between 1 and 3650)");
    expect(lower).toContain("terms_url ~* '^https?://'");
  });

  it("records the environments and whether the plan is declared only", () => {
    expect(lower).toContain("environments uuid[] not null default '{}'");
    expect(lower).toContain("declared_only boolean not null default true");
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("apx-1.2 (#6099)");
  });
});
