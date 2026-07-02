/**
 * Structural assertions over the MCP date/time version-tag migration (#3671, V2-MCP-18.4).
 *
 * V131 adds `version_tag` to `apiome.mcp_endpoint_versions`: a human-readable UTC date/time label
 * (e.g. `2026-06-26T14:03Z`) that is unique per endpoint and immutable. The column is added
 * NULLable, back-filled from each row's discovery time (around the V128 immutability trigger), made
 * NOT NULL, then constrained UNIQUE(endpoint_id, version_tag). These tests verify that contract
 * structurally without a live database (this package's suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V131__mcp_catalog_version_datetime_tag_3671.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP date/time version-tag migration", () => {
  it("is present in scripts/ and ordered after V130", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V130__mcp_catalog_scores_jobs_invocations_3655.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds the version_tag column idempotently and NULLable first", () => {
    expect(lower).toMatch(/add column if not exists version_tag text/);
  });

  it("enforces NOT NULL only after the backfill", () => {
    const backfillAt = lower.indexOf("row_number() over");
    const notNullAt = lower.indexOf("alter column version_tag set not null");
    expect(backfillAt).toBeGreaterThanOrEqual(0);
    expect(notNullAt).toBeGreaterThan(backfillAt);
  });

  it("back-fills using the same minute-precision UTC format the app emits", () => {
    expect(sql).toContain("'YYYY-MM-DD\"T\"HH24:MI\"Z\"'");
    expect(sql).toContain("AT TIME ZONE 'UTC'");
    expect(sql).toContain("COALESCE(discovered_at, created_at)");
  });

  it("disambiguates same-minute collisions during backfill via a window rank", () => {
    expect(lower).toContain("row_number() over");
    expect(lower).toContain("partition by");
  });

  it("toggles the V128 immutability trigger off for the backfill and restores it", () => {
    const disableAt = sql.indexOf("DISABLE TRIGGER trigger_mcp_endpoint_versions_immutable");
    const enableAt = sql.indexOf("ENABLE TRIGGER trigger_mcp_endpoint_versions_immutable");
    expect(disableAt).toBeGreaterThanOrEqual(0);
    expect(enableAt).toBeGreaterThan(disableAt);
  });

  it("constrains version_tag unique per endpoint (the addressability backstop)", () => {
    expect(lower).toContain(
      "mcp_endpoint_versions_endpoint_tag_unique unique (endpoint_id, version_tag)",
    );
  });

  it("documents the column", () => {
    expect(lower).toContain("comment on column mcp_endpoint_versions.version_tag");
  });
});
