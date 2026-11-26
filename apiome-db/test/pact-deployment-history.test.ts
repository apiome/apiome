/**
 * Structural assertions over the deployment-history migration (#6951, PFX-5.7).
 *
 * V446 orders an environment's deployments, so the environment page's **Deployment history**
 * reads one page without sorting every deployment ever recorded. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first.
 *   2. The history index leads with (environment_id, tenant_id), so the environment reference's
 *      check is still served once the older index is dropped.
 *   3. It changes no column or rule of the table.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V446__pact_deployment_history_6951.sql";

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

describe("deployment-history migration (PFX-5.7)", () => {
  it("is present in scripts/ and ordered after the environments migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V435__pact_environments_6918.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("builds the ordered history index before dropping the one it replaces", () => {
    const history = ddl.indexOf(
      "create index if not exists idx_deployed_version_environment_history on deployed_version (environment_id, tenant_id, seq desc)",
    );
    const dropped = ddl.indexOf("drop index if exists idx_deployed_version_environment;");
    expect(history).toBeGreaterThan(0);
    expect(dropped).toBeGreaterThan(history);
  });

  it("changes no column or rule of the table", () => {
    expect(ddl).not.toContain("alter table");
    expect(ddl).not.toContain("constraint");
  });
});
