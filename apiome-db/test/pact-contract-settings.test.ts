/**
 * Structural assertions over the Contracts settings migration (#7312, PFX-8.15).
 *
 * V457 stores the commit-status and agent switches, and lets a migrated secret wait for its value:
 *
 *   1. It sets its own search path first and comes after the retention policy migration.
 *   2. One settings row per tenant, removed with the tenant; the defaults match the mockup (statuses
 *      on, bi-directional off; agents read and draft, never write, until allowed).
 *   3. A secret has a value unless it is waiting for one, and a waiting webhook is off.
 *   4. The new foreign key is indexed.
 *
 * `apiome-rest/tests/test_pact_contract_settings_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V457__pact_contract_settings_7312.sql";

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

describe("pact contract settings migration (PFX-8.15)", () => {
  it("is present in scripts/ and ordered after the retention policy migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V456__pact_retention_policy_7311.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("keeps one settings row per tenant with the mockup's defaults", () => {
    expect(ddl).toContain("tenant_id uuid primary key references tenants(id) on delete cascade");
    for (const column of ["status_consumer_commit", "status_provider_commit", "agent_read", "agent_draft"]) {
      expect(ddl).toContain(`${column} boolean not null default true`);
    }
    for (const column of ["status_bidirectional", "agent_publish", "agent_record"]) {
      expect(ddl).toContain(`${column} boolean not null default false`);
    }
  });

  it("lets a secret wait for its value, and only then go without one", () => {
    expect(ddl).toContain("alter column secret_ciphertext drop not null");
    expect(ddl).toContain(
      "check ((awaiting_value and secret_ciphertext is null and key_version is null) " +
        "or (not awaiting_value and secret_ciphertext is not null and key_version is not null)) not valid",
    );
    expect(ddl).toContain("validate constraint pact_secret_value_or_awaiting_check");
    expect(ddl).toContain("check (origin is null or origin in ('migration'))");
  });

  it("keeps a webhook waiting for a secret turned off", () => {
    expect(ddl).toContain("add column if not exists awaiting_secrets boolean not null default false");
    expect(ddl).toContain("check (not awaiting_secrets or not enabled) not valid");
    expect(ddl).toContain("validate constraint pact_webhook_awaiting_secrets_off_check");
  });

  it("indexes the new foreign key", () => {
    expect(ddl).toContain("on pact_contract_settings (updated_by) where updated_by is not null");
  });
});
