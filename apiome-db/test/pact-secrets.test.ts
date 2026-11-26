/**
 * Structural assertions over the workspace-secrets migration (#6957, PFX-6.5).
 *
 * V450 adds the named secrets that webhooks and verification targets refer to. DB-free contract
 * tests pin it:
 *
 *   1. It sets its own search path first and comes after the contract-health migration.
 *   2. `pact_secret` has no plaintext column: the value is ciphertext plus its key version.
 *   3. Names are shaped and unique per workspace; the table is a composite reference target.
 *   4. Webhooks gain `secret_refs`; targets gain the `secret` reference kind with a shaped ref.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V450__pact_secrets_6957.sql";

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

describe("workspace-secrets migration (PFX-6.5)", () => {
  it("is present in scripts/ and ordered after the contract-health migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V449__pact_health_window_6955.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("stores a secret as ciphertext and its key version only", () => {
    const table = ddl.match(/create table if not exists pact_secret \((.*?)\);/)?.[1] ?? "";
    expect(table).toContain("secret_ciphertext bytea not null");
    expect(table).toContain("key_version integer not null");
    expect(table).not.toMatch(/\bvalue text\b|\bplaintext\b|\bsecret_value\b/);
  });

  it("shapes names and keeps one per workspace", () => {
    expect(ddl).toContain("check (name ~ '^[a-za-z][a-za-z0-9_]{0,63}$')");
    expect(ddl).toContain("constraint uq_pact_secret_name unique (tenant_id, name)");
    expect(ddl).toContain("constraint uq_pact_secret_id_tenant unique (id, tenant_id)");
    expect(ddl).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
  });

  it("indexes the user references", () => {
    expect(ddl).toContain("on pact_secret (created_by) where created_by is not null");
    expect(ddl).toContain("on pact_secret (updated_by) where updated_by is not null");
  });

  it("records the names a webhook refers to", () => {
    expect(ddl).toContain(
      "alter table pact_webhook add column if not exists secret_refs text[] not null default array[]::text[]",
    );
  });

  it("lets a target refer to a secret by a shaped name", () => {
    expect(ddl).toContain("check (auth_kind in ('none', 'env', 'stored', 'secret'))");
    expect(ddl).toContain("check (auth_kind <> 'secret' or auth_ref ~ '^[a-za-z][a-za-z0-9_]{0,63}$')");
  });
});
