/**
 * Structural assertions over the MCP public-endpoints read-view migration
 * (#3671, V2-MCP-23.6 / MCAT-1.6).
 *
 * V134 adds `apiome.mcp_v_public_endpoints`, a credential-free read view that exposes only enabled,
 * published, public-visible catalog endpoints (mirroring V095's `mcp_v_public_specs`). It backs
 * apiome-browse's public MCP pages, so the acceptance-critical properties are: the
 * published+public+enabled filter (private endpoints can never appear), the current-version
 * score/grade join, and that the raw `endpoint_url` (which may carry credentials) is never
 * selected — only a userinfo-stripped host. These tests verify the migration's shape without a
 * live database (this package's suite is DB-free; end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V134__mcp_catalog_public_endpoints_view_3671.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP public-endpoints read-view migration", () => {
  it("is present in scripts/ and ordered after V133", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V133__mcp_catalog_discovery_backoff_quarantine_3675.sql"),
    );
  });

  it("creates the view idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create or replace view apiome\.mcp_v_public_endpoints as/);
  });

  it("filters to enabled, published, public-visible, non-deleted endpoints", () => {
    expect(lower).toContain("e.deleted_at is null");
    expect(lower).toContain("e.enabled is true");
    expect(lower).toContain("e.published is true");
    expect(lower).toMatch(/e\.visibility = 'public'::apiome\.visibility_type/);
  });

  it("joins the current snapshot's quality score and grade", () => {
    expect(lower).toMatch(
      /left join apiome\.mcp_version_scores s on s\.version_id = e\.current_version_id/,
    );
    for (const col of ["s.score", "s.grade", "s.scored_at"]) {
      expect(lower).toContain(col);
    }
  });

  it("never exposes the raw endpoint_url (credential safety) — host only", () => {
    // The raw URL may embed userinfo (https://user:secret@host/…); it must not be a selected column.
    expect(lower).not.toMatch(/^\s*e\.endpoint_url\s*,/m);
    expect(lower).not.toMatch(/e\.endpoint_url\s+as\b/);
    // Host is derived with the userinfo-stripping expression apiome-rest uses.
    expect(sql).toMatch(
      /substring\(e\.endpoint_url from ':\/\/\(\?:\[\^@\/\]\*@\)\?\(\[\^:\/\?#\]\+\)'\) AS host/,
    );
  });

  it("exposes the columns the public browse pages consume", () => {
    for (const col of [
      "e.id",
      "e.tenant_id",
      "e.name",
      "e.slug",
      "e.category",
      "e.transport",
      "e.description",
      "e.current_version_id",
      "e.last_discovered_at",
      "e.updated_at",
    ]) {
      expect(lower).toContain(col);
    }
  });

  it("documents the view and all of its columns", () => {
    expect(lower).toMatch(/comment on view apiome\.mcp_v_public_endpoints is/);
    const columnComments = (sql.match(/COMMENT ON COLUMN apiome\.mcp_v_public_endpoints\./g) ?? [])
      .length;
    // 14 columns: id, tenant_id, name, slug, category, transport, description, current_version_id,
    // host, score, grade, scored_at, last_discovered_at, updated_at.
    expect(columnComments).toBe(14);
  });
});
