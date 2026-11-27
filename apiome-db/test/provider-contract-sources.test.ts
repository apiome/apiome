/**
 * Structural assertions over the provider-contract standing-sources migration (#7304, PFX-8.7).
 *
 * V453 adds `provider_contract_source`: one row per provider pacticipant naming where its contract
 * is published from automatically. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first and comes after the pact matrix scale migration.
 *   2. Both references are composite `(id, tenant_id)` keys (no cross-workspace row).
 *   3. A deleted repository clears the repository id only; a deleted pacticipant takes the row.
 *   4. The repository source is all or nothing, and every foreign key has an index.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V453__provider_contract_sources_7304.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("provider-contract standing sources migration (PFX-8.7)", () => {
  it("is present in scripts/ and ordered after the pact matrix scale migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V452__pact_matrix_scale_6958.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("keeps one row per pacticipant, removed with it", () => {
    expect(ddl).toContain("constraint provider_contract_source_pkey primary key (pacticipant_id, tenant_id)");
    expect(ddl).toContain(
      "foreign key (pacticipant_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
  });

  it("names a repository of the same workspace and forgets only its id when it is deleted", () => {
    expect(ddl).toContain(
      "foreign key (repository_id, tenant_id) references tenant_repositories (id, tenant_id) on delete set null (repository_id)",
    );
  });

  it("refuses a repository without a path and a branch", () => {
    expect(ddl).toContain(
      "check (repository_id is null or (repository_path is not null and repository_branch is not null))",
    );
    expect(ddl).toContain("check (repository_branch is null or btrim(repository_branch) <> '')");
  });

  it("is off by default for project publishes", () => {
    expect(ddl).toContain("on_project_publish boolean not null default false");
  });

  it("indexes every reference", () => {
    expect(ddl).toContain("on provider_contract_source (repository_id, tenant_id) where repository_id is not null");
    expect(ddl).toContain("on provider_contract_source (tenant_id)");
    expect(ddl).toContain("on provider_contract_source (updated_by) where updated_by is not null");
  });
});
