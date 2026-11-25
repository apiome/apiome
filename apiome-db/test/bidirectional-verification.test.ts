/**
 * Structural assertions over the bi-directional verification migration (#6927, PFX-2.3).
 *
 * V439 lets `verification_result` hold Apiome's pact-to-OpenAPI comparisons next to the results
 * Pact verifiers publish. DB-free contract tests pin its rules:
 *
 *   1. **A kind's columns go together**: a native result has no contract and no comparison; a
 *      bi-directional one has both.
 *   2. **One comparison per pair**: unique over (pact version, provider version) for the
 *      bi-directional rows.
 *   3. **Nothing crosses a provider**: the contract is referenced by `(id, provider_id)`.
 *   4. **A result goes with its contract** (ON DELETE CASCADE).
 *
 * These must stay in lock-step with apiome-rest's `app.bidirectional_store`;
 * `apiome-rest/tests/test_bidirectional_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V439__bidirectional_verification_6927.sql";

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

describe("bi-directional verification migration (PFX-2.3)", () => {
  it("is present in scripts/ and ordered after the results and the provider contracts", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V434__pact_verification_result_6917.sql"));
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V438__provider_contracts_6925.sql"));
  });

  it("sets its own search path", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBe(ddl.indexOf("set search_path"));
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("alter table"));
  });

  it("adds the columns idempotently, every existing row native", () => {
    expect(ddl).toContain("add column if not exists kind varchar(16) not null default 'native'");
    expect(ddl).toContain("add column if not exists provider_contract_id uuid");
    expect(ddl).toContain("add column if not exists comparison jsonb");
  });

  it("keeps a kind's columns together", () => {
    expect(ddl).toContain("kind = 'native' and provider_contract_id is null and comparison is null");
    expect(ddl).toContain(
      "kind = 'bidirectional' and provider_contract_id is not null and comparison is not null and jsonb_typeof(comparison) = 'object'",
    );
  });

  it("compares a pact version with a provider version once", () => {
    expect(ddl).toContain(
      "create unique index if not exists verification_result_bidirectional_pair_key on verification_result (pact_version_id, provider_version_id) where kind = 'bidirectional'",
    );
  });

  it("references the contract of the same provider, cascading, and indexes the reference", () => {
    expect(ddl).toContain(
      "foreign key (provider_contract_id, provider_id) references apiome.provider_contract (id, provider_id) on delete cascade",
    );
    expect(ddl).toContain(
      "on verification_result (provider_contract_id, provider_id) where provider_contract_id is not null",
    );
  });
});
