/**
 * Structural assertions over the MCP categorization model & manual tags migration (#3693,
 * V2-MCP-23.3 / MCAT-9.3).
 *
 * V365 adds `mcp_categories` — the category lookup, with built-in rows (`tenant_id` NULL) seeded
 * alongside tenant-defined ones — and `mcp_endpoint_tags`, zero or more normalized free tags per
 * catalog endpoint. These tests verify that contract without a live database (this package's suite
 * is DB-free); `apiome-rest/tests/test_mcp_categorization_db.py` applies it for real.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V365__mcp_categories_and_tags_3693.sql";

// The executable SQL only (line comments stripped), so prose in the header cannot satisfy or trip
// an assertion about the statements the migration runs.
let codeLower = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  codeLower = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n")
    .toLowerCase();
});

describe("MCP categories and tags migration", () => {
  it("is present in scripts/ and ordered after V364", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V364__mcp_endpoint_health_checks_3713.sql"),
    );
  });

  it("scopes to the apiome schema", () => {
    expect(codeLower).toContain("set search_path to apiome, public");
  });

  it("creates the category lookup with a nullable tenant for built-ins", () => {
    expect(codeLower).toContain("create table if not exists mcp_categories");
    expect(codeLower).toMatch(/tenant_id uuid references tenants\(id\) on delete cascade,/);
    expect(codeLower).toContain("slug varchar(64) not null");
    expect(codeLower).toContain("label varchar(128) not null");
  });

  it("keeps built-in and per-tenant slugs unique separately", () => {
    expect(codeLower).toMatch(
      /create unique index if not exists uq_mcp_categories_builtin_slug\s+on mcp_categories\(slug\) where tenant_id is null/,
    );
    expect(codeLower).toMatch(
      /create unique index if not exists uq_mcp_categories_tenant_slug\s+on mcp_categories\(tenant_id, slug\) where tenant_id is not null/,
    );
  });

  it("seeds the built-in vocabulary idempotently", () => {
    expect(codeLower).toContain("on conflict (slug) where tenant_id is null do nothing");
    for (const slug of ["developer-tools", "databases", "security", "other"]) {
      expect(codeLower).toContain(`(null, '${slug}',`);
    }
  });

  it("constrains slugs and tags to their normalized spelling", () => {
    expect(codeLower).toContain("check (slug ~ '^[a-z0-9][a-z0-9-]{0,63}$')");
    expect(codeLower).toContain("check (tag ~ '^[a-z0-9][a-z0-9._:-]{0,63}$')");
  });

  it("creates one tag row per endpoint and tag, removed with the endpoint", () => {
    expect(codeLower).toContain("create table if not exists mcp_endpoint_tags");
    expect(codeLower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
    );
    expect(codeLower).toContain("primary key (endpoint_id, tag)");
  });

  it("indexes tag lookups within a tenant", () => {
    expect(codeLower).toMatch(
      /create index if not exists idx_mcp_endpoint_tags_tenant_tag\s+on mcp_endpoint_tags\(tenant_id, tag\)/,
    );
  });

  it("does not add a foreign key from mcp_endpoints.category (the lookup is lenient)", () => {
    expect(codeLower).not.toMatch(/alter table\s+mcp_endpoints/);
  });
});
