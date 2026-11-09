/**
 * Structural assertions over the MCP endpoint health-checks migration (#3713, V2-MCP-27.3 / MCAT-13.3).
 *
 * V364 adds `mcp_endpoint_health_checks`: one row per lightweight reachability probe of a catalog
 * endpoint (the MCP `initialize` handshake only), with its up/down status, latency and — for a failed
 * probe — the stable discovery error code. Rows cascade with their endpoint and are indexed for the
 * per-endpoint newest-first reads (history, the "latest probe" due-selection) and age-based pruning.
 * These tests verify that contract without a live database (this package's suite is DB-free);
 * `apiome-rest/tests/test_mcp_health_checks_db.py` applies it for real.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V364__mcp_endpoint_health_checks_3713.sql";

// The executable SQL only (line comments stripped), so prose in the header cannot satisfy or trip
// an assertion about the statements the migration runs.
let codeLower = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  codeLower = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("MCP endpoint health-checks migration", () => {
  it("is present in scripts/ and ordered after V363", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V363__mcp_discovery_sweep_runs_3676.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(codeLower).toContain("set search_path to apiome, public");
  });

  it("creates the table idempotently with status, latency and error code", () => {
    expect(codeLower).toContain("create table if not exists mcp_endpoint_health_checks");
    for (const column of [
      "checked_at timestamp with time zone not null default current_timestamp",
      "status varchar(8) not null",
      "latency_ms integer",
      "error_code varchar(64)",
    ]) {
      expect(codeLower).toContain(column);
    }
  });

  it("removes an endpoint's history with the endpoint", () => {
    expect(codeLower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
  });

  it("constrains status to up or down and latency to non-negative", () => {
    expect(codeLower).toMatch(/check \(status in \('up', 'down'\)\)/);
    expect(codeLower).toContain("latency_ms is null or latency_ms >= 0");
  });

  it("never stores the endpoint URL", () => {
    expect(codeLower).not.toMatch(/\bendpoint_url\b/);
  });

  it("indexes the per-endpoint newest-first reads and age-based pruning", () => {
    expect(codeLower).toMatch(
      /create index if not exists idx_mcp_endpoint_health_checks_endpoint_checked_at\s+on mcp_endpoint_health_checks\(endpoint_id, checked_at desc\)/,
    );
    expect(codeLower).toMatch(
      /create index if not exists idx_mcp_endpoint_health_checks_checked_at\s+on mcp_endpoint_health_checks\(checked_at\)/,
    );
  });

  it("documents the new table and columns", () => {
    expect(codeLower).toContain("comment on table mcp_endpoint_health_checks");
    expect(codeLower).toContain("comment on column mcp_endpoint_health_checks.status");
  });
});
