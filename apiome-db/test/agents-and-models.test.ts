/**
 * Structural assertions over the agent and model entities migration (CDG-5.2, #5980).
 *
 * V297 adds `catalog_models`, `catalog_agents`, the agent ↔ agent-key link and the agent ↔ consumer
 * link (one consumer per agent per project), and widens three checks: a consumer contract may come
 * from an agent, and agents and models may have an owner team. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V297__agents_and_models_cdg_5_2.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("agents and models migration (CDG-5.2)", () => {
  it("is present in scripts/ and ordered after V296", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V296__mcp_registry_connector_cdg_4_4.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the four tables idempotently", () => {
    for (const table of ["catalog_models", "catalog_agents", "catalog_agent_keys", "catalog_agent_consumers"]) {
      expect(lower).toContain(`create table if not exists ${table} (`);
    }
  });

  it("keeps a model's hosting, an agent's status and both slugs in shape", () => {
    expect(lower).toMatch(/hosting in \('api', 'self_hosted'\)/);
    expect(lower).toMatch(/status in \('active', 'retired'\)/);
    expect(lower).toMatch(/catalog_agents_slug_shape_check/);
    expect(lower).toMatch(/catalog_models_slug_shape_check/);
    expect(lower).toContain("deprecated_at timestamp with time zone");
  });

  it("makes slugs unique among live rows only", () => {
    expect(lower).toMatch(/idx_catalog_agents_tenant_slug\s+on catalog_agents \(tenant_id, slug\)\s+where deleted_at is null/);
    expect(lower).toMatch(/idx_catalog_models_tenant_slug\s+on catalog_models \(tenant_id, slug\)\s+where deleted_at is null/);
  });

  it("gives a key at most one agent and an agent one consumer per project", () => {
    expect(lower).toContain("catalog_agent_keys_one_agent_per_key unique (api_key_id)");
    expect(lower).toContain("primary key (agent_id, project_id)");
  });

  it("widens the contract source and the owner kinds", () => {
    expect(lower).toContain("check (source in ('pact', 'manual', 'agent'))");
    expect(lower).toMatch(/entity_owners_kind_check\s+check \(entity_kind in \([^)]*'agent', 'model'\)\)/);
    expect(lower).toMatch(/unowned_findings_kind_check\s+check \(entity_kind in \([^)]*'agent', 'model'\)\)/);
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("cdg-5.2 (#5980)");
  });
});
