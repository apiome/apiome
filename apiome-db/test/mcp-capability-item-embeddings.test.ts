/**
 * Structural assertions over the MCP capability-item embedding migration (#4661, V2-MCP-35.2).
 *
 * V149 adds `apiome.mcp_capability_items.embedding`: the optional per-item capability embedding
 * backing the cross-server capability search semantic signal, reusing the existing pgvector setup
 * (the `vector` extension, the 2000-dimension Ollama convention of V060/V063, and the cosine-HNSW
 * index pattern of V102/V143). These tests verify the migration's contract without a live database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V149__mcp_capability_item_embeddings_4661.sql";

let sql = "";
let lower = "";
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

describe("MCP capability-item embedding migration", () => {
  it("is present in scripts/ and ordered after V148", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V148__mcp_discovery_provenance_4659.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds a nullable 2000-dim embedding column idempotently to mcp_capability_items", () => {
    expect(lower).toMatch(
      /alter table apiome\.mcp_capability_items\s+add column if not exists embedding vector\(2000\) null/,
    );
    expect(lower).not.toMatch(/embedding vector\(2000\) not null/);
  });

  it("indexes populated embeddings with a partial cosine HNSW index", () => {
    expect(lower).toMatch(
      /create index if not exists idx_mcp_capability_items_embedding_hnsw\s+on apiome\.mcp_capability_items using hnsw \(embedding vector_cosine_ops\)\s+where embedding is not null/,
    );
  });

  it("documents the new column", () => {
    expect(lower).toMatch(/comment on column apiome\.mcp_capability_items\.embedding is/);
  });

  it("is additive: only ADD COLUMN / CREATE INDEX, no drops or table rewrites", () => {
    expect(codeLower).not.toMatch(/alter table(?!\s+apiome\.mcp_capability_items\s+add column)/);
    expect(codeLower).not.toMatch(/\bdrop\b/);
    expect(codeLower).not.toMatch(/create table/);
  });
});
