/**
 * Structural assertions over the pact verification-result migration (#6917, PFX-1.4).
 *
 * V434 stores what Pact verifiers publish. DB-free contract tests pin its rules:
 *
 *   1. **A result never changes** (a BEFORE UPDATE trigger; only the database's own SET NULLs pass).
 *   2. **Results are numbered per pact version**, unique with it and with (pact version, provider
 *      version, number).
 *   3. **Nothing crosses a tenant**: the pact version, the provider version and the provider are
 *      referenced by composite keys, and so is the optional CTG-4.3 report.
 *   4. **A result goes with its pact and its provider version** (both cascade).
 *   5. **A CTG-4.3 report is linked, not copied**: deleting it clears only the link.
 *
 * These must stay in lock-step with apiome-rest's `app.verification_result_store`;
 * `apiome-rest/tests/test_verification_result_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V434__pact_verification_result_6917.sql";

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

describe("pact verification-result migration (PFX-1.4)", () => {
  it("is present in scripts/ and ordered after pact publication", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V433__pact_publication_6915.sql"));
  });

  it("sets its own search path before using uuid_generate_v4()", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBeGreaterThan(-1);
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("uuid_generate_v4()"));
  });

  it("creates the table idempotently with the columns can-i-deploy reads", () => {
    expect(ddl).toContain("create table if not exists verification_result (");
    expect(ddl).toContain("success boolean not null");
    expect(ddl).toContain("test_results jsonb not null default '[]'::jsonb");
    expect(ddl).toContain("check (jsonb_typeof(test_results) = 'array')");
  });

  it("numbers results per pact version", () => {
    expect(ddl).toContain("check (number >= 1)");
    expect(ddl).toContain("constraint verification_result_number_key unique (pact_version_id, number)");
    expect(ddl).toContain(
      "constraint verification_result_version_number_key unique (pact_version_id, provider_version_id, number)",
    );
  });

  it("joins only rows of one tenant and one pair, cascading the pact and the provider version", () => {
    expect(ddl).toContain(
      "foreign key (pact_version_id, consumer_id, provider_id) references pact_version (id, consumer_id, provider_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (provider_version_id, provider_id) references pacticipant_version (id, pacticipant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (provider_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade",
    );
  });

  it("links a CTG-4.3 report in the same tenant and keeps the result when the report goes", () => {
    expect(ddl).toContain("add constraint provider_verification_report_id_tenant_key unique (id, tenant_id)");
    expect(ddl).toContain(
      "foreign key (provider_verification_report_id, tenant_id) references provider_verification_report (id, tenant_id) on delete set null (provider_verification_report_id)",
    );
  });

  it("refuses updates except the database's own reference clears", () => {
    expect(ddl).toContain("create or replace function apiome.verification_result_immutable()");
    expect(ddl).toContain("- 'created_by' - 'provider_verification_report_id'");
    expect(ddl).toContain("errcode = 'restrict_violation'");
    expect(ddl).toContain("before update on verification_result for each row");
  });

  it("indexes every foreign key that does not reference users", () => {
    for (const index of [
      "on verification_result (provider_id, tenant_id, consumer_id, seq desc)",
      "on verification_result (pact_version_id, consumer_id, provider_id)",
      "on verification_result (provider_version_id, provider_id)",
      "on verification_result (provider_verification_report_id, tenant_id) where provider_verification_report_id is not null",
    ]) {
      expect(ddl).toContain(index);
    }
  });
});
