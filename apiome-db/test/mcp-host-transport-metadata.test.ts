/**
 * Structural assertions over the MCP host & transport metadata migration (#4655, V2-MCP-34.1).
 *
 * V146 adds two nullable columns to `apiome.mcp_endpoints` — `transport_metadata` (JSONB) and
 * `transport_metadata_at` — where the discovery pipeline persists the *latest* non-invasive transport
 * facts it observed at handshake (host, TLS certificate summary, notable response headers, connect
 * timing). They live on the (mutable) endpoint rather than the immutable version snapshot because the
 * facts are volatile and refresh on every successful discovery. These tests verify the migration's
 * contract — additive, nullable, no default, documented — without a live database (this package's
 * suite is DB-free; the SQL is asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V146__mcp_host_transport_metadata_4655.sql";

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

describe("MCP host & transport metadata migration", () => {
  it("is present in scripts/ and ordered after V145", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V145__mcp_catalog_digest_configs_4654.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds both columns to mcp_endpoints idempotently", () => {
    expect(lower).toContain("alter table mcp_endpoints");
    expect(lower).toMatch(
      /add column if not exists transport_metadata jsonb/,
    );
    expect(lower).toMatch(
      /add column if not exists transport_metadata_at timestamp with time zone/,
    );
  });

  it("keeps the columns nullable with no default (absent until first discovery)", () => {
    expect(codeLower).not.toContain("not null");
    expect(codeLower).not.toContain("default");
  });

  it("is additive only — no destructive statements in the executable SQL", () => {
    // The rollback DROP COLUMN lives only in the leading comment block, never in executable SQL.
    expect(codeLower).not.toContain("drop column");
    expect(codeLower).not.toContain("drop table");
    expect(codeLower).not.toContain("delete from");
    expect(codeLower).not.toContain("truncate");
  });

  it("documents both new columns", () => {
    expect(lower).toMatch(
      /comment on column mcp_endpoints\.transport_metadata is/,
    );
    expect(lower).toMatch(
      /comment on column mcp_endpoints\.transport_metadata_at is/,
    );
  });
});
