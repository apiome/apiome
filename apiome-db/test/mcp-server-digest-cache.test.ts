/**
 * Structural assertions over the MCP server-digest cache migration (#4649, V2-MCP-32.5).
 *
 * V144 adds `apiome.mcp_server_digests`: the per-surface cache of the natural-language server digest +
 * usage examples, keyed on `mcp_endpoint_versions.surface_fingerprint` so the AI summary is computed
 * once per surface and regenerated only when the surface (and thus the fingerprint) changes. These tests
 * verify the migration's contract — the fingerprint-keyed table, its digest/examples/model/provenance
 * columns, and documentation — without a live database (this package's suite is DB-free; the SQL is
 * asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V144__mcp_server_digest_cache_4649.sql";

let sql = "";
let lower = "";
// The executable SQL only (line comments stripped), so assertions about which statements the
// migration runs are not tripped by prose in its `-- …` header (which mentions "foreign key").
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

describe("MCP server-digest cache migration", () => {
  it("is present in scripts/ and ordered after V143", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V143__mcp_similar_servers_embeddings_4648.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the digest cache table idempotently, keyed on surface_fingerprint", () => {
    expect(lower).toMatch(
      /create table if not exists apiome\.mcp_server_digests/,
    );
    // The cache key is the surface fingerprint — one digest per surface, shared across tenants/versions.
    expect(lower).toMatch(/surface_fingerprint\s+text\s+primary key/);
  });

  it("stores the digest text, the example calls (JSONB), and the model provenance", () => {
    expect(lower).toMatch(/digest\s+text\s+not null/);
    expect(lower).toMatch(/examples\s+jsonb\s+not null/);
    expect(lower).toMatch(/\bmodel\s+text\b/);
    expect(lower).toMatch(/generated_at\s+timestamptz\s+not null/);
  });

  it("does not couple the cache to a version row via a foreign key", () => {
    // surface_fingerprint is a content hash shared across rows/tenants, not a row identity — the cache
    // must survive pruning of any single version snapshot, so no FK to mcp_endpoint_versions.
    expect(codeLower).not.toContain("references apiome.mcp_endpoint_versions");
    expect(codeLower).not.toContain("foreign key");
  });

  it("documents the table and its columns", () => {
    expect(lower).toMatch(/comment on table apiome\.mcp_server_digests is/);
    expect(lower).toMatch(/comment on column apiome\.mcp_server_digests\.digest is/);
    expect(lower).toMatch(/comment on column apiome\.mcp_server_digests\.examples is/);
  });
});
