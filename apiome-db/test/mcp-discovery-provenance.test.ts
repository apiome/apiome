/**
 * Structural assertions over the MCP discovery-provenance migration (#4659, V2-MCP-34.5).
 *
 * V148 records how the catalog came to know things: `mcp_endpoints.added_via` (how the endpoint
 * entered the catalog — manual/registry/import, defaulted to `manual` which is also the exact
 * backfill since manual registration is the only creation path that has ever existed) and
 * `mcp_endpoint_versions.discovery_trigger` / `discovery_job_id` (which discovery run produced the
 * snapshot). Existing snapshots are back-filled from the completed job history — only from jobs whose
 * `result` says `changed = true`, so a later unchanged re-run can never claim a snapshot it did not
 * produce — around the V128 immutability trigger, the V131 precedent. `discovery_job_id` is
 * deliberately NOT a foreign key: an `ON DELETE SET NULL` FK would UPDATE the write-once version rows
 * when jobs are purged (which endpoint teardown does before deleting versions) and trip the
 * immutability trigger. These tests verify that contract structurally without a live database (this
 * package's suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V148__mcp_discovery_provenance_4659.sql";

let sql = "";
let lower = "";
// The executable SQL only (line comments stripped), so assertions about which statements the
// migration runs are not tripped by prose in its `-- …` header (which mentions "DROP COLUMN").
let codeLower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  codeLower = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("MCP discovery provenance migration", () => {
  it("is present in scripts/ and ordered after V147", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V147__mcp_server_branding_4656.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds added_via to mcp_endpoints idempotently, defaulted to manual", () => {
    expect(lower).toContain("alter table mcp_endpoints");
    expect(lower).toMatch(
      /add column if not exists added_via varchar\(32\) not null default 'manual'/,
    );
  });

  it("constrains added_via to the known origins (drop-then-add for idempotence)", () => {
    expect(lower).toContain(
      "drop constraint if exists mcp_endpoints_added_via_check",
    );
    expect(lower).toMatch(
      /check \(added_via in \('manual', 'registry', 'import'\)\)/,
    );
  });

  it("adds the version provenance columns idempotently and NULLable", () => {
    expect(lower).toContain("alter table mcp_endpoint_versions");
    expect(lower).toMatch(/add column if not exists discovery_trigger varchar\(32\)/);
    expect(lower).toMatch(/add column if not exists discovery_job_id uuid/);
    // NULL means "unrecorded": the version columns carry no NOT NULL and no DEFAULT.
    expect(codeLower).not.toMatch(/discovery_trigger varchar\(32\) not null/);
    expect(codeLower).not.toMatch(/discovery_job_id uuid not null/);
  });

  it("keeps discovery_job_id a plain audit pointer, never a foreign key", () => {
    // A REFERENCES clause would need ON DELETE SET NULL, which UPDATEs the write-once
    // version rows on job purge and trips the V128 immutability trigger mid-teardown.
    expect(codeLower).not.toMatch(/discovery_job_id uuid[^,\n]*references/);
  });

  it("constrains discovery_trigger to the V130 job trigger domain, allowing NULL", () => {
    expect(lower).toContain(
      "drop constraint if exists mcp_endpoint_versions_discovery_trigger_check",
    );
    expect(lower).toMatch(
      /check \(discovery_trigger is null or discovery_trigger in \('manual', 'sweep', 'registry'\)\)/,
    );
  });

  it("back-fills only from completed jobs that actually produced the snapshot", () => {
    expect(lower).toContain("state = 'completed'");
    expect(sql).toContain("result ->> 'changed' = 'true'");
    expect(sql).toContain("result ->> 'version_id'");
    // Earliest producing job wins when several match.
    expect(lower).toContain("distinct on (j.version_id)");
    expect(lower).toContain("order by j.version_id, j.created_at asc, j.id asc");
  });

  it("never overwrites an already-attributed snapshot during backfill", () => {
    expect(lower).toContain("and v.discovery_trigger is null");
    expect(lower).toContain("and v.discovery_job_id is null");
  });

  it("guards the uuid cast so a malformed job result cannot abort the backfill", () => {
    expect(sql).toMatch(/~\* '\^\[0-9a-f\]\{8\}-/);
  });

  it("toggles the V128 immutability trigger off for the backfill and restores it", () => {
    const disableAt = sql.indexOf(
      "DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable",
    );
    const enableAt = sql.indexOf(
      "ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable",
    );
    expect(disableAt).toBeGreaterThanOrEqual(0);
    expect(enableAt).toBeGreaterThan(disableAt);
    // The attribution UPDATE runs inside the disabled window.
    const updateAt = lower.indexOf("update mcp_endpoint_versions v");
    expect(updateAt).toBeGreaterThan(disableAt);
    expect(updateAt).toBeLessThan(enableAt);
  });

  it("is additive only — no destructive statements in the executable SQL", () => {
    // The rollback DROP COLUMNs live only in the leading comment block, never in executable SQL.
    expect(codeLower).not.toContain("drop column");
    expect(codeLower).not.toContain("drop table");
    expect(codeLower).not.toContain("delete from");
    expect(codeLower).not.toContain("truncate");
  });

  it("documents every new column", () => {
    expect(lower).toMatch(/comment on column mcp_endpoints\.added_via is/);
    expect(lower).toMatch(
      /comment on column mcp_endpoint_versions\.discovery_trigger is/,
    );
    expect(lower).toMatch(
      /comment on column mcp_endpoint_versions\.discovery_job_id is/,
    );
  });
});
