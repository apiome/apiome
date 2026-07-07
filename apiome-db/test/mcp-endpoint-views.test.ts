/**
 * Structural assertions over the MCP per-user seen-marker migration (#4640, V2-MCP-30.5).
 *
 * V142 adds `apiome.mcp_endpoint_views`: the per-user, per-endpoint "last-viewed version" marker
 * backing the "changed since last view" digest. These tests verify the migration's contract —
 * table + columns + the one-marker-per-(user, endpoint) unique key + the three foreign keys with
 * their delete behaviour + the reverse-lookup index + documentation — without a live database (this
 * package's suite is DB-free; the SQL is asserted structurally, end-to-end application is proven
 * elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V142__mcp_endpoint_views_4640.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP endpoint seen-marker migration", () => {
  it("is present in scripts/ and ordered after V141", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V141__export_field_identities_3880.sql"),
    );
  });

  it("creates the table idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_endpoint_views/);
  });

  it("defines every mcp_endpoint_views column from the ticket's field set", () => {
    for (const col of [
      "id",
      "user_id",
      "endpoint_id",
      "last_seen_version_id",
      "seen_at",
      "created_at",
    ]) {
      // Column declared at the start of a line (after indentation), not merely mentioned in prose.
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
    }
  });

  it("keys the marker to its user and endpoint, cascading on either delete", () => {
    expect(lower).toMatch(/user_id uuid not null references users\(id\) on delete cascade/);
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
  });

  it("treats last_seen_version_id as a nullable soft pointer (SET NULL on version prune)", () => {
    expect(lower).toMatch(
      /last_seen_version_id uuid references mcp_endpoint_versions\(id\) on delete set null/,
    );
    // Not NOT NULL: a pruned version leaves the marker with a NULL pointer, never a dangling row.
    expect(lower).not.toMatch(/last_seen_version_id uuid not null/);
  });

  it("enforces exactly one marker per (user, endpoint) for the upsert to advance in place", () => {
    expect(lower).toMatch(/unique\s*\(user_id, endpoint_id\)/);
  });

  it("timestamps default to CURRENT_TIMESTAMP so a bare insert is a valid marker", () => {
    expect(sql).toMatch(/seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP/);
    expect(sql).toMatch(/created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP/);
  });

  it("indexes the endpoint reverse lookup", () => {
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_endpoint_views\(endpoint_id\)/,
    );
  });

  it("documents the table and all of its columns", () => {
    expect(lower).toMatch(/comment on table mcp_endpoint_views is/);
    const columnComments = (sql.match(/COMMENT ON COLUMN mcp_endpoint_views\./g) ?? []).length;
    // 6 columns: id, user_id, endpoint_id, last_seen_version_id, seen_at, created_at — each documented.
    expect(columnComments).toBe(6);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid), matching the neighbouring MCP tables", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("is purely additive: no ALTER of pre-existing tables, no destructive statements", () => {
    expect(lower).not.toMatch(/alter table/);
    expect(lower).not.toMatch(/drop table(?! if exists apiome\.mcp_endpoint_views)/);
  });
});
