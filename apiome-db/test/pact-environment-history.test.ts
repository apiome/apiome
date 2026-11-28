/**
 * Structural assertions over the environment history migration (#7310, PFX-8.13).
 *
 * V455 adds what the Environments page's **History** view tells: can-i-deploy's verdict when a
 * deployment or release was recorded, who ended it, why a deployment ended, and which deployment a
 * new one replaced. DB-free contract tests pin it:
 *
 *   1. It sets its own search path first and comes after the pacticipant rename migration.
 *   2. The verdict and the end reason take only their known words.
 *   3. The guards still keep the history: the new columns move only when a record ends (or, for
 *      `replaced_id`, are cleared).
 *   4. The backfill runs with the guard off and turns it back on.
 *   5. Every history read and the new foreign key are indexed.
 *
 * `apiome-rest/tests/test_pact_environment_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V455__pact_environment_history_7310.sql";

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

describe("pact environment history migration (PFX-8.13)", () => {
  it("is present in scripts/ and ordered after the pacticipant rename migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V454__pacticipant_rename_7307.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("stores the verdict at the time with its three words, on both tables", () => {
    const check = "check (recorded_verdict is null or recorded_verdict in ('deployable', 'not-deployable', 'unknown'))";
    expect(ddl.split(check).length - 1).toBe(2);
  });

  it("says why a deployment ended", () => {
    expect(ddl).toContain("check (ended_reason is null or ended_reason in ('replaced', 'undeployed'))");
    expect(ddl).toContain("add column if not exists replaced_id uuid");
    expect(ddl).toContain("references deployed_version (id) on delete set null");
  });

  it("lets the ending columns move only when the deployment ends", () => {
    expect(ddl).toContain("ending boolean := old.currently_deployed and not new.currently_deployed");
    expect(ddl).toContain(
      "(ending or (new.ended_actor_label is not distinct from old.ended_actor_label " +
        "and new.ended_reason is not distinct from old.ended_reason))",
    );
    expect(ddl).toContain("(new.replaced_id is null or new.replaced_id is not distinct from old.replaced_id)");
  });

  it("keeps a release's other columns fixed", () => {
    expect(ddl).toContain("released_version % can only change whether it is supported");
    expect(ddl).toContain("- 'recorded_verdict' - 'ended_actor_label')");
  });

  it("re-enables the guard after the backfill", () => {
    const off = ddl.indexOf("alter table deployed_version disable trigger trg_deployed_version_history_guard");
    const on = ddl.indexOf("alter table deployed_version enable trigger trg_deployed_version_history_guard");
    expect(off).toBeGreaterThan(-1);
    expect(on).toBeGreaterThan(off);
    expect(ddl.slice(off, on)).toContain("set ended_reason = 'replaced'");
  });

  it("indexes each history read and the new reference", () => {
    expect(ddl).toContain("on deployed_version (tenant_id, created_at desc, id desc)");
    expect(ddl).toContain(
      "on deployed_version (tenant_id, undeployed_at desc, id desc) " +
        "where undeployed_at is not null and ended_reason is distinct from 'replaced'",
    );
    expect(ddl).toContain("on deployed_version (replaced_id) where replaced_id is not null");
    expect(ddl).toContain("on released_version (tenant_id, created_at desc, id desc)");
    expect(ddl).toContain(
      "on released_version (tenant_id, support_ended_at desc, id desc) where support_ended_at is not null",
    );
  });
});
