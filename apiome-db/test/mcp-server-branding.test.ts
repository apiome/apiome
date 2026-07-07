/**
 * Structural assertions over the MCP server branding migration (#4656, V2-MCP-34.2).
 *
 * V147 adds one nullable column to `apiome.mcp_endpoint_versions` — `server_branding` (JSONB) — where
 * discovery persists the *validated* branding a server advertised in its `initialize` `serverInfo`
 * (an https-only, SSRF-guarded website/icon URL set). It lives on the immutable version snapshot,
 * alongside the other `serverInfo` columns, but is deliberately excluded from the surface fingerprint
 * (that exclusion is enforced in the application, not the schema). These tests verify the migration's
 * contract — additive, nullable, no default, documented — without a live database (this package's
 * suite is DB-free; the SQL is asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V147__mcp_server_branding_4656.sql";

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

describe("MCP server branding migration", () => {
  it("is present in scripts/ and ordered after V146", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V146__mcp_host_transport_metadata_4655.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds the column to mcp_endpoint_versions idempotently", () => {
    expect(lower).toContain("alter table mcp_endpoint_versions");
    expect(lower).toMatch(/add column if not exists server_branding jsonb/);
  });

  it("keeps the column nullable with no default (absent until branding is discovered)", () => {
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

  it("documents the new column", () => {
    expect(lower).toMatch(
      /comment on column mcp_endpoint_versions\.server_branding is/,
    );
  });
});
