/**
 * Structural assertions over the Backstage and Compass import migration (CDG-5.5, #5983).
 *
 * V299 adds the import reports (`catalog_import_runs`), the staged suggestions
 * (`catalog_import_suggestions`) and the `component` entity kind (`catalog_components`), and widens
 * the graph, owner and declared-dependency kinds by `component`. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V299__catalog_components_cdg_5_5.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("catalog components migration (CDG-5.5)", () => {
  it("is present in scripts/ and ordered after V298", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V298__gateway_configs_cdg_5_3.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("keeps one report per source ref, cascading from its repository", () => {
    expect(lower).toContain("create table if not exists catalog_import_runs (");
    expect(lower).toContain("constraint catalog_import_runs_identity_key unique (tenant_id, source_ref)");
    expect(lower).toContain("repository_id uuid references tenant_repositories(id) on delete cascade");
    expect(lower).toContain("check (jsonb_typeof(unmapped) = 'array')");
    expect(lower).toContain("check (jsonb_typeof(entity_refs) = 'array')");
  });

  it("keys suggestions by source, kind and external ref, and stamps every decision", () => {
    expect(lower).toContain("create table if not exists catalog_import_suggestions (");
    expect(lower).toContain("run_id uuid not null references catalog_import_runs(id) on delete cascade");
    expect(lower).toMatch(/catalog_import_suggestions_identity_key\s+unique \(tenant_id, source, suggestion_kind, external_ref\)/);
    expect(lower).toContain("check (status in ('suggested', 'accepted', 'dismissed'))");
    expect(lower).toContain("check ((status = 'suggested') = (decided_at is null))");
    expect(lower).toContain("check (status <> 'accepted' or (entity_kind is not null and entity_id is not null))");
  });

  it("keeps live component slugs and external refs unique", () => {
    expect(lower).toContain("create table if not exists catalog_components (");
    expect(lower).toContain("check (category in ('component', 'system', 'domain'))");
    expect(lower).toMatch(/idx_catalog_components_tenant_slug\s+on catalog_components \(tenant_id, slug\)\s+where deleted_at is null/);
    expect(lower).toMatch(
      /idx_catalog_components_external\s+on catalog_components \(tenant_id, source, external_ref\)\s+where deleted_at is null/,
    );
  });

  it("adds component to the graph, owner and declared-dependency kinds", () => {
    expect(lower).toMatch(/from_kind in \([^)]*'component'\)/);
    expect(lower).toMatch(/to_kind in \([^)]*'component'\)/);
    expect(lower).toMatch(/entity_owners_kind_check\s+check \(entity_kind in \([^)]*'component'\)\)/);
    expect(lower).toMatch(/unowned_findings_kind_check\s+check \(entity_kind in \([^)]*'component'\)\)/);
    expect(lower).toMatch(/catalog_unresolved_dependencies_from_kind_check check \(from_kind in \([^)]*'component'\s*\)\)/);
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("cdg-5.5 (#5983)");
  });
});
