/**
 * Structural assertions over the provider contract migration (#6925, PFX-2.1).
 *
 * V438 stores the OpenAPI documents providers publish for bi-directional contract testing.
 * DB-free contract tests pin its rules:
 *
 *   1. **Content is stored once**: a provider contract is unique per provider and SHA-256.
 *   2. **Write-once per provider version**: one publication per provider version.
 *   3. **Nothing crosses a tenant**: the provider and the source project are referenced by
 *      `(id, tenant_id)`; a publication joins a version and a contract of one provider only.
 *   4. **A contract goes with its provider**, while deleting the source project or version only
 *      clears the link.
 *
 * These must stay in lock-step with apiome-rest's `app.provider_contract_store`;
 * `apiome-rest/tests/test_provider_contract_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V438__provider_contracts_6925.sql";

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

describe("provider contract migration (PFX-2.1)", () => {
  it("is present in scripts/ and ordered after the pact tables", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V433__pact_publication_6915.sql"));
  });

  it("sets its own search path before using uuid_generate_v4()", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBeGreaterThan(-1);
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("uuid_generate_v4()"));
  });

  it("creates the two tables idempotently", () => {
    expect(ddl).toContain("create table if not exists provider_contract (");
    expect(ddl).toContain("create table if not exists provider_contract_publication (");
  });

  it("stores a document once per provider and content hash", () => {
    expect(ddl).toContain("check (sha ~ '^[0-9a-f]{64}$')");
    expect(ddl).toContain("content jsonb not null");
    expect(ddl).toContain("check (jsonb_typeof(content) = 'object')");
    expect(ddl).toContain("constraint provider_contract_content_key unique (provider_id, sha)");
  });

  it("keeps one publication per provider version", () => {
    expect(ddl).toContain("constraint provider_contract_publication_version_key unique (provider_version_id)");
  });

  it("names where a document came from, and only for an Apiome source", () => {
    expect(ddl).toContain("check (source in ('inline', 'apiome'))");
    expect(ddl).toContain("source = 'inline' and source_project_id is null and source_version_id is null");
    expect(ddl).toContain("source = 'apiome' and source_project_slug is not null and source_version_label is not null");
  });

  it("references the provider and the source project inside one tenant", () => {
    expect(ddl).toContain(
      "foreign key (provider_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (source_project_id, tenant_id) references projects (id, tenant_id) on delete set null (source_project_id)",
    );
  });

  it("joins a publication to a version and a contract of the same provider, cascading both", () => {
    expect(ddl).toContain("constraint provider_contract_id_provider_key unique (id, provider_id)");
    expect(ddl).toContain(
      "foreign key (provider_version_id, provider_id) references pacticipant_version (id, pacticipant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (provider_contract_id, provider_id) references provider_contract (id, provider_id) on delete cascade",
    );
  });

  it("clears, not cascades, the link to a deleted Apiome version", () => {
    expect(ddl).toContain("foreign key (source_version_id) references versions (id) on delete set null");
  });

  it("indexes every foreign key that does not reference users", () => {
    for (const index of [
      "on provider_contract (provider_id, tenant_id)",
      "on provider_contract_publication (provider_id, tenant_id)",
      "on provider_contract_publication (provider_version_id, provider_id)",
      "on provider_contract_publication (provider_contract_id, provider_id)",
      "on provider_contract_publication (source_project_id, tenant_id) where source_project_id is not null",
      "on provider_contract_publication (source_version_id) where source_version_id is not null",
    ]) {
      expect(ddl).toContain(index);
    }
  });
});
