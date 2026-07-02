/**
 * Structural assertions over the MCP version + change-record migration (#3653, V2-MCP-15.3).
 *
 * V128 adds `apiome.mcp_endpoint_versions` (immutable, tagged discovery snapshots) and
 * `apiome.mcp_version_changes` (the per-item added/removed/modified diff each snapshot introduced), and
 * retro-fits the two foreign keys V126/V127 deferred until this table existed
 * (`mcp_endpoints.current_version_id` and `mcp_capability_items.version_id`). These tests verify the
 * migration's contract — tables + columns + constraints + the immutability trigger + the deferred
 * FKs — without a live database (this package's suite is DB-free; the SQL is asserted structurally,
 * end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V128__mcp_catalog_versions_changes_3653.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP version + change-record migration", () => {
  it("is present in scripts/ and ordered after V127", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V127__mcp_catalog_capability_items_3652.sql"),
    );
  });

  it("creates both tables idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_endpoint_versions/);
    expect(lower).toMatch(/create table if not exists mcp_version_changes/);
  });

  it("defines every mcp_endpoint_versions column from the ticket's field set", () => {
    for (const col of [
      "id",
      "endpoint_id",
      "version_seq",
      "protocol_version",
      "server_name",
      "server_title",
      "server_version",
      "instructions",
      "capabilities",
      "surface_fingerprint",
      "discovered_at",
      "created_at",
    ]) {
      // Column declared at the start of a line (after indentation), not merely mentioned in prose.
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
    }
  });

  it("defines every mcp_version_changes column from the ticket's field set", () => {
    for (const col of [
      "version_id",
      "change_type",
      "item_type",
      "item_name",
      "detail",
    ]) {
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
    }
  });

  it("keys snapshots to their endpoint and cascades on endpoint delete", () => {
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
  });

  it("enforces a unique, positive, monotonic version_seq per endpoint", () => {
    expect(lower).toMatch(/unique\s*\(endpoint_id, version_seq\)/);
    expect(lower).toMatch(/check\s*\(version_seq >= 1\)/);
    expect(sql).toMatch(/version_seq INTEGER NOT NULL/);
  });

  it("constrains change_type to the three diff directions", () => {
    expect(lower).toMatch(/check\s*\(change_type in \(/);
    for (const kind of ["'added'", "'removed'", "'modified'"]) {
      expect(sql).toContain(kind);
    }
  });

  it("links change rows to the version that introduced them, cascading on version delete", () => {
    expect(lower).toMatch(
      /version_id uuid not null references mcp_endpoint_versions\(id\) on delete cascade/,
    );
  });

  it("models the diff payload columns: item identity + before/after detail", () => {
    expect(sql).toMatch(/item_type VARCHAR\(\d+\) NOT NULL/);
    expect(sql).toMatch(/item_name VARCHAR\(\d+\) NOT NULL/);
    expect(sql).toMatch(/detail JSONB NOT NULL DEFAULT '\{\}'::jsonb/);
  });

  it("keeps both tables write-once: no updated_at column is declared", () => {
    // No `updated_at` column declaration (it may appear in prose explaining why it is absent).
    expect(sql).not.toMatch(/^\s+updated_at\s/m);
  });

  it("enforces immutability with a BEFORE UPDATE trigger that raises", () => {
    expect(lower).toContain("create or replace function mcp_forbid_row_mutation()");
    expect(lower).toContain("raise exception");
    // Both tables get the guard, and it is BEFORE UPDATE only (DELETE must remain free for cascades).
    expect(lower).toMatch(/before update on mcp_endpoint_versions/);
    expect(lower).toMatch(/before update on mcp_version_changes/);
    expect(lower).not.toMatch(/before (update or )?delete/);
  });

  it("retro-fits the FK V126 deferred: mcp_endpoints.current_version_id -> versions", () => {
    expect(lower).toMatch(
      /alter table mcp_endpoints\s+add constraint \w+\s+foreign key \(current_version_id\) references mcp_endpoint_versions\(id\) on delete set null/,
    );
  });

  it("retro-fits the FK V127 deferred: mcp_capability_items.version_id -> versions", () => {
    expect(lower).toMatch(
      /alter table mcp_capability_items\s+add constraint \w+\s+foreign key \(version_id\) references mcp_endpoint_versions\(id\) on delete cascade/,
    );
  });

  it("drops the FK constraints before (re)adding them for idempotent re-runs", () => {
    expect(lower).toMatch(/drop constraint if exists mcp_endpoints_current_version_fk/);
    expect(lower).toMatch(/drop constraint if exists mcp_capability_items_version_fk/);
  });

  it("indexes version history and per-item change tracing", () => {
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_endpoint_versions\(endpoint_id, discovered_at desc\)/,
    );
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_version_changes\(version_id, change_type\)/,
    );
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_version_changes\(item_type, item_name\)/,
    );
  });

  it("documents both tables and all of their columns", () => {
    expect(lower).toMatch(/comment on table mcp_endpoint_versions is/);
    expect(lower).toMatch(/comment on table mcp_version_changes is/);
    const versionColumnComments = (sql.match(/COMMENT ON COLUMN mcp_endpoint_versions\./g) ?? []).length;
    const changeColumnComments = (sql.match(/COMMENT ON COLUMN mcp_version_changes\./g) ?? []).length;
    // 12 version columns; 7 change columns (id, version_id, change_type, item_type, item_name,
    // detail, created_at) — each documented.
    expect(versionColumnComments).toBe(12);
    expect(changeColumnComments).toBe(7);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });
});
