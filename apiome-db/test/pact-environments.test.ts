/**
 * Structural assertions over the pact environments migration (#6918, PFX-1.5).
 *
 * V435 stores environments and what is deployed or released to them. DB-free contract tests pin
 * its rules:
 *
 *   1. **Environment names are unique per tenant** and contain no whitespace.
 *   2. **One version is currently deployed** per environment, pacticipant and application
 *      instance (a partial unique index).
 *   3. **Deployment history is kept**: a deployed_version row can only be marked undeployed, once.
 *   4. **A version is released to an environment once**; only its support flag moves.
 *   5. **Nothing crosses a tenant**: version, pacticipant and environment are referenced by
 *      composite keys.
 *   6. **Records go with their environment, pacticipant and version** (every reference cascades).
 *
 * These must stay in lock-step with apiome-rest's `app.pact_environment_store`;
 * `apiome-rest/tests/test_pact_environment_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V435__pact_environments_6918.sql";

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

describe("pact environments migration (PFX-1.5)", () => {
  it("is present in scripts/ and ordered after verification results", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V434__pact_verification_result_6917.sql"));
  });

  it("sets its own search path before using uuid_generate_v4()", () => {
    expect(ddl.indexOf("set search_path to apiome, public")).toBeGreaterThan(-1);
    expect(ddl.indexOf("set search_path to apiome, public")).toBeLessThan(ddl.indexOf("uuid_generate_v4()"));
  });

  it("creates the three tables idempotently", () => {
    for (const table of ["pact_environment", "deployed_version", "released_version"]) {
      expect(ddl).toContain(`create table if not exists ${table} (`);
    }
  });

  it("keeps environment names unique per tenant and free of whitespace", () => {
    expect(ddl).toContain("constraint pact_environment_tenant_name_key unique (tenant_id, name)");
    expect(ddl).toContain("check (name <> '' and name !~ '[[:space:][:cntrl:]]')");
    expect(ddl).toContain("production boolean not null default false");
    expect(ddl).toContain("contract_required boolean not null default false");
    expect(ddl).toContain("check (jsonb_typeof(contacts) = 'array')");
  });

  it("allows one current deployment per environment, pacticipant and application instance", () => {
    expect(ddl).toContain(
      "create unique index if not exists uq_deployed_version_current on deployed_version (environment_id, pacticipant_id, coalesce(application_instance, '')) where currently_deployed",
    );
    expect(ddl).toContain("check (currently_deployed = (undeployed_at is null))");
  });

  it("only lets a deployment be marked undeployed, once", () => {
    expect(ddl).toContain("create or replace function apiome.deployed_version_history_guard()");
    expect(ddl).toContain("- 'created_by' - 'currently_deployed' - 'undeployed_at'");
    expect(ddl).toContain("(old.currently_deployed and not new.currently_deployed)");
    expect(ddl).toContain("before update on deployed_version for each row");
  });

  it("records a release once per version and environment and only moves its support flag", () => {
    expect(ddl).toContain("constraint released_version_version_environment_key unique (version_id, environment_id)");
    expect(ddl).toContain("check (currently_supported = (support_ended_at is null))");
    expect(ddl).toContain("- 'created_by' - 'currently_supported' - 'support_ended_at' - 'updated_at'");
    expect(ddl).toContain("before update on released_version for each row");
  });

  it("joins only rows of one tenant and cascades every reference", () => {
    expect(ddl).toContain("constraint pact_environment_id_tenant_key unique (id, tenant_id)");
    for (const table of ["deployed_version", "released_version"]) {
      expect(ddl).toContain(
        `constraint ${table}_version_fk foreign key (version_id, pacticipant_id) references pacticipant_version (id, pacticipant_id) on delete cascade`,
      );
      expect(ddl).toContain(
        `constraint ${table}_pacticipant_fk foreign key (pacticipant_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade`,
      );
      expect(ddl).toContain(
        `constraint ${table}_environment_fk foreign key (environment_id, tenant_id) references pact_environment (id, tenant_id) on delete cascade`,
      );
    }
  });

  it("indexes every foreign key that does not reference users", () => {
    for (const index of [
      "on deployed_version (environment_id, tenant_id)",
      "on deployed_version (pacticipant_id, tenant_id, seq desc)",
      "on deployed_version (version_id, pacticipant_id)",
      "on released_version (environment_id, tenant_id, pacticipant_id)",
      "on released_version (pacticipant_id, tenant_id, seq desc)",
      "on released_version (version_id, pacticipant_id)",
    ]) {
      expect(ddl).toContain(index);
    }
  });
});
