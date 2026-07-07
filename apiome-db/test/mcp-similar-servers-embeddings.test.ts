/**
 * Structural assertions over the MCP similar-servers embedding migration (#4648, V2-MCP-32.4).
 *
 * V143 adds `apiome.mcp_endpoint_versions.mcp_capability_embedding`: the optional per-snapshot
 * capability embedding backing the "similar servers" semantic nearest-neighbour signal, reusing the
 * existing pgvector setup (the `vector` extension, the 2000-dimension Ollama convention of V060/V063,
 * and the cosine-HNSW index pattern of V102). These tests verify the migration's contract — the
 * additive nullable vector column, its partial cosine-HNSW index, and documentation — without a live
 * database (this package's suite is DB-free; the SQL is asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V143__mcp_similar_servers_embeddings_4648.sql";

let sql = "";
let lower = "";
// The executable SQL only (line comments stripped), so assertions about which statements the
// migration runs are not tripped by the rollback notes in its `-- …` header.
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

describe("MCP similar-servers embedding migration", () => {
  it("is present in scripts/ and ordered after V142", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V142__mcp_endpoint_views_4640.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds a nullable 2000-dim capability embedding column idempotently to mcp_endpoint_versions", () => {
    expect(lower).toMatch(
      /alter table apiome\.mcp_endpoint_versions\s+add column if not exists mcp_capability_embedding vector\(2000\) null/,
    );
    // Nullable by design: NULL until backfilled / whenever embeddings are disabled.
    expect(lower).not.toMatch(/mcp_capability_embedding vector\(2000\) not null/);
  });

  it("indexes the populated embeddings with a partial cosine HNSW index (mirroring V102)", () => {
    expect(lower).toMatch(
      /create index if not exists idx_mcp_endpoint_versions_capability_embedding_hnsw\s+on apiome\.mcp_endpoint_versions using hnsw \(mcp_capability_embedding vector_cosine_ops\)\s+where mcp_capability_embedding is not null/,
    );
  });

  it("documents the new column", () => {
    expect(lower).toMatch(
      /comment on column apiome\.mcp_endpoint_versions\.mcp_capability_embedding is/,
    );
  });

  it("is additive: only ADD COLUMN / CREATE INDEX, no drops or table rewrites", () => {
    // Executable statements only (rollback notes in the header comment are excluded). The one ALTER is
    // the additive ADD COLUMN; there is no CREATE/DROP TABLE and no DROP outside the comment.
    expect(codeLower).not.toMatch(/alter table(?!\s+apiome\.mcp_endpoint_versions\s+add column)/);
    expect(codeLower).not.toMatch(/\bdrop\b/);
    expect(codeLower).not.toMatch(/create table/);
  });
});
