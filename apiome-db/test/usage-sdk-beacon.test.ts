/**
 * Structural assertions over the SDK compatibility beacon migration (#4736, RDG-1.7 / SGD-3.1).
 *
 * V380 stores opt-in SDK beacon counts. The promises pinned here are the privacy ones: only the five
 * allowed facts (SDK, SDK version, API version + revision, operation, outcome) and a count can be
 * stored, every text column is pattern-checked, and rows age out with the tier's rollup retention.
 * Must stay in lock-step with apiome-rest's `app.sdk_beacon`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V380__usage_sdk_beacon_rdg_1_7.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

/** The CREATE TABLE block. */
function table(): string {
  const start = statements.indexOf("create table if not exists usage_sdk_beacon_daily (");
  return statements.slice(start, statements.indexOf(");", start));
}

describe("SDK beacon migration", () => {
  it("is ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V379__comment_thread_origin_col_4_4.sql"));
  });

  it("scopes rows to a tenant, project, source and published revision, all cascading", () => {
    const section = table();
    expect(section).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    expect(section).toContain("source_id uuid not null references usage_source(id) on delete cascade");
    expect(section).toContain("spec_revision_id uuid not null references versions(id) on delete cascade");
  });

  it("stores only the five allowed facts and counters", () => {
    const columns = table()
      .split("\n")
      .map((line) => line.trim().match(/^([a-z_]+) /)?.[1])
      .filter((name): name is string => Boolean(name) && name !== "constraint" && name !== "create");
    expect(new Set(columns)).toEqual(
      new Set([
        "tenant_id",
        "project_id",
        "source_id",
        "day",
        "spec_revision_id",
        "api_version",
        "sdk_name",
        "sdk_version",
        "operation_id",
        "outcome",
        "calls",
        "first_seen_at",
        "last_seen_at",
      ]),
    );
  });

  it("closes the outcome vocabulary and pattern-checks every text column", () => {
    const section = table();
    expect(section).toContain("outcome in ('ok', 'client_error', 'server_error', 'network', 'incompatible')");
    for (const column of ["api_version", "sdk_name", "sdk_version", "operation_id"]) {
      expect(section).toMatch(new RegExp(`check \\(${column} ~ '\\^`));
    }
  });

  it("prunes past the tier's rollup retention", () => {
    expect(statements).toContain("create or replace function purge_usage_sdk_beacons(");
    expect(statements).toContain("from apiome.usage_retention(p_now) r");
    expect(statements).toContain("b.day < r.rollup_cutoff");
  });
});
