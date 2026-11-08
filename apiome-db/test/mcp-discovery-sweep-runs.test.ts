/**
 * Structural assertions over the MCP discovery sweep-runs migration (#3676, V2-MCP-19.4 / MCAT-5.4).
 *
 * V363 gives the periodic re-discovery sweep a record of its own: `mcp_discovery_sweep_runs` holds one
 * row per tick (timing, the bounds it ran under, due / dispatched / coalesced / enqueue-failed counts,
 * and whether it completed or was halted by the kill switch), and `mcp_discovery_jobs.sweep_run_id`
 * links each job a tick created back to it. The outcome counters (changed / unchanged / failed / in
 * flight) are deliberately not stored on the run — they are aggregated from the linked jobs at read
 * time so they always reconcile with the job log — and the link is `ON DELETE SET NULL` so pruning old
 * runs never removes job history. These tests verify that contract without a live database (this
 * package's suite is DB-free); `apiome-rest/tests/test_mcp_sweep_runs_db.py` applies it for real.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V363__mcp_discovery_sweep_runs_3676.sql";

let lower = "";
// The executable SQL only (line comments stripped), so prose in the header cannot satisfy or trip
// an assertion about the statements the migration runs.
let codeLower = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  codeLower = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("MCP discovery sweep-runs migration", () => {
  it("is present in scripts/ and ordered after V362", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V362__source_provenance_2365.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the runs table idempotently with timing, bounds and tick counters", () => {
    expect(codeLower).toContain("create table if not exists mcp_discovery_sweep_runs");
    for (const column of [
      "started_at timestamp with time zone not null default current_timestamp",
      "finished_at timestamp with time zone",
      "status varchar(16) not null default 'running'",
      "max_concurrency integer",
      "endpoint_timeout_seconds integer",
      "due_count integer not null default 0",
      "dispatched_count integer not null default 0",
      "deduplicated_count integer not null default 0",
      "enqueue_failed_count integer not null default 0",
    ]) {
      expect(codeLower).toContain(column);
    }
  });

  it("constrains status to running, completed, halted or failed, and counts to non-negative", () => {
    expect(codeLower).toMatch(/check \(status in \('running', 'completed', 'halted', 'failed'\)\)/);
    expect(codeLower).toContain("due_count >= 0");
    expect(codeLower).toContain("enqueue_failed_count >= 0");
  });

  it("does not store outcome counters that the job rows already hold", () => {
    // Whole words: `enqueue_failed_count` is a tick counter and legitimately contains `failed_count`.
    for (const column of ["changed_count", "unchanged_count", "failed_count"]) {
      expect(codeLower).not.toMatch(new RegExp(`\\b${column}\\b`));
    }
  });

  it("links jobs to their run without ever deleting a job when a run is pruned", () => {
    expect(codeLower).toMatch(
      /alter table mcp_discovery_jobs\s+add column if not exists sweep_run_id uuid\s+references mcp_discovery_sweep_runs\(id\) on delete set null/,
    );
    expect(codeLower).not.toMatch(/sweep_run_id[^;]*on delete cascade/);
  });

  it("indexes the reads the status endpoint and pruning make", () => {
    expect(codeLower).toMatch(
      /create index if not exists idx_mcp_discovery_sweep_runs_started_at\s+on mcp_discovery_sweep_runs\(started_at desc\)/,
    );
    expect(codeLower).toMatch(
      /create index if not exists idx_mcp_discovery_jobs_sweep_run_id\s+on mcp_discovery_jobs\(sweep_run_id\) where sweep_run_id is not null/,
    );
  });

  it("documents the new table and columns", () => {
    expect(codeLower).toContain("comment on table mcp_discovery_sweep_runs");
    expect(codeLower).toContain("comment on column mcp_discovery_jobs.sweep_run_id");
  });
});
