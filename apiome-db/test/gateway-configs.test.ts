/**
 * Structural assertions over the gateway configs migration (CDG-5.3, #5981).
 *
 * V298 adds `catalog_gateway_configs` — one live row per (connector, environment) — and widens the
 * graph's node kinds and the owner kinds by `gateway_config`. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V298__gateway_configs_cdg_5_3.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("gateway configs migration (CDG-5.3)", () => {
  it("is present in scripts/ and ordered after V297", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V297__agents_and_models_cdg_5_2.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("keeps one live row per connector and environment, and live slugs unique", () => {
    expect(lower).toContain("create table if not exists catalog_gateway_configs (");
    expect(lower).toContain("connector_id uuid not null references catalog_connectors(id) on delete cascade");
    expect(lower).toContain("environment text not null default ''");
    expect(lower).toMatch(
      /idx_catalog_gateway_configs_connector_env\s+on catalog_gateway_configs \(tenant_id, connector_id, environment\)\s+where deleted_at is null/,
    );
    expect(lower).toMatch(/idx_catalog_gateway_configs_tenant_slug\s+on catalog_gateway_configs \(tenant_id, slug\)\s+where deleted_at is null/);
  });

  it("stores posture as an object and losses as an array", () => {
    expect(lower).toContain("check (jsonb_typeof(posture) = 'object')");
    expect(lower).toContain("check (jsonb_typeof(declared_losses) = 'array')");
  });

  it("adds gateway_config to the graph and owner kinds", () => {
    expect(lower).toMatch(/from_kind in \([^)]*'gateway_config'\)/);
    expect(lower).toMatch(/to_kind in \([^)]*'gateway_config'\)/);
    expect(lower).toMatch(/entity_owners_kind_check\s+check \(entity_kind in \([^)]*'gateway_config'\)\)/);
    expect(lower).toMatch(/unowned_findings_kind_check\s+check \(entity_kind in \([^)]*'gateway_config'\)\)/);
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("cdg-5.3 (#5981)");
  });
});
