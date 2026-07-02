/**
 * Structural assertions over the MCP capability-item store migration (#3652, V2-MCP-15.2).
 *
 * V127 adds `apiome.mcp_capability_items`: one normalized row per discovered MCP tool / resource /
 * resource_template / prompt, so a server's surface is queryable (search/diff/render) rather than
 * an opaque blob. These tests verify the migration's contract — table + columns + indexes + the
 * tolerance rules for older (2025-03-26) servers — without a live database (this package's suite is
 * DB-free; the SQL is asserted structurally, end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V127__mcp_catalog_capability_items_3652.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP capability-item store migration", () => {
  it("is present in scripts/ and ordered after V126", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V126__mcp_catalog_endpoints_data_model_3651.sql"),
    );
  });

  it("creates the table idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_capability_items/);
  });

  it("defines every column from the ticket's field set", () => {
    for (const col of [
      "id",
      "version_id",
      "item_type",
      "name",
      "title",
      "description",
      "input_schema",
      "output_schema",
      "annotations",
      "uri",
      "uri_template",
      "raw",
      "ordinal",
    ]) {
      // Column declared at the start of a line (after indentation), not merely mentioned in prose.
      expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
    }
  });

  it("constrains item_type to the four MCP capability kinds", () => {
    expect(lower).toMatch(/check\s*\(item_type in \(/);
    for (const kind of ["'tool'", "'resource'", "'resource_template'", "'prompt'"]) {
      expect(sql).toContain(kind);
    }
  });

  it("requires version_id but defers the FK to V128 (no FK to a not-yet-existing table)", () => {
    expect(sql).toMatch(/version_id UUID NOT NULL/);
    // mcp_endpoint_versions is created in V128; V127 must not reference it.
    expect(lower).not.toContain("references mcp_endpoint_versions");
    expect(lower).not.toMatch(/foreign key\s*\(version_id\)/);
  });

  it("tolerates older 2025-03-26 servers: title and output_schema are nullable", () => {
    // Each optional column is declared on its own line with no NOT NULL qualifier.
    expect(sql).toMatch(/^\s*title VARCHAR\(\d+\),\s*$/m);
    expect(sql).toMatch(/^\s*output_schema JSONB,\s*$/m);
  });

  it("keeps identity + fidelity columns mandatory", () => {
    expect(sql).toMatch(/item_type VARCHAR\(\d+\) NOT NULL/);
    expect(sql).toMatch(/name VARCHAR\(\d+\) NOT NULL/);
    expect(sql).toMatch(/raw JSONB NOT NULL/);
    expect(sql).toMatch(/ordinal INTEGER NOT NULL/);
  });

  it("guards ordinal as a non-negative list position", () => {
    expect(lower).toMatch(/check\s*\(ordinal >= 0\)/);
  });

  it("indexes (version_id, item_type) and (name) for diff/render and lookup", () => {
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_capability_items\(version_id, item_type\)/,
    );
    expect(lower).toMatch(
      /create index if not exists \w+\s+on mcp_capability_items\(name\)/,
    );
  });

  it("provides the FTS GIN index over name + description (MCAT-9.2)", () => {
    expect(lower).toContain("using gin (to_tsvector('english'");
    expect(lower).toMatch(/coalesce\(name, ''\) \|\| ' ' \|\| coalesce\(description, ''\)/);
  });

  it("documents the table and all of its columns", () => {
    expect(lower).toMatch(/comment on table mcp_capability_items is/);
    const columnComments = (sql.match(/COMMENT ON COLUMN mcp_capability_items\./g) ?? []).length;
    // 14 columns: id, version_id, item_type, name, title, description, input_schema,
    // output_schema, annotations, uri, uri_template, raw, ordinal, created_at.
    expect(columnComments).toBe(14);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });
});
