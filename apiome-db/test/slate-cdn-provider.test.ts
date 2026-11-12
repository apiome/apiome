/**
 * Structural assertions over the Slate CDN / edge provider migration
 * (Slate 10.2, private-suite#120).
 *
 * The migration adds one CDN provider per lane with a sealed purge credential, an
 * append-only log of every purge sent to it, and widens the cache audit to cover
 * provider changes. V187's "dispatched needs an attached edge" CHECK must survive
 * untouched. These tests verify the DDL contract without a live database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V368__slate_cdn_provider_10_2.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("slate cdn provider migration", () => {
  it("is present in scripts/ and ordered after V367", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V367__component_governance_2364.sql"),
    );
  });

  it("creates one provider per environment", () => {
    expect(sql).toContain("create table if not exists apiome.slate_cdn_providers");
    expect(sql).toMatch(/environment_id\s+uuid not null unique/);
    expect(sql).toContain("check (provider in ('cloudflare', 'fastly', 'custom'))");
  });

  it("stores the credential only as ciphertext with its key version", () => {
    expect(sql).toMatch(/credential_ciphertext\s+bytea not null/);
    expect(sql).toMatch(/credential_key_version\s+integer not null/);
    // No column a plaintext secret could land in.
    expect(sql).not.toMatch(/\b(api_token|api_key|secret|password)\s+text/);
  });

  it("constrains each provider's public coordinate and the custom header", () => {
    expect(sql).toContain("slate_cdn_providers_cloudflare_target");
    expect(sql).toContain("target ~ '^[0-9a-f]{32}$'");
    expect(sql).toContain("slate_cdn_providers_fastly_target");
    expect(sql).toContain("slate_cdn_providers_custom_target");
    expect(sql).toContain("target like 'https://%'");
    expect(sql).toContain("(provider = 'custom') = (auth_header_name is not null)");
    expect(sql).toContain("slate_cdn_providers_header_token");
  });

  it("logs dispatches with a status-bound error code", () => {
    expect(sql).toContain("create table if not exists apiome.slate_cdn_purge_dispatches");
    expect(sql).toContain("check (trigger in ('deploy', 'manual'))");
    expect(sql).toContain("check (mode in ('urls', 'purge-all'))");
    expect(sql).toContain("check (status in ('succeeded', 'failed', 'skipped'))");
    expect(sql).toContain("(status = 'succeeded') = (error_code is null)");
  });

  it("widens the cache audit to cover provider changes, idempotently", () => {
    expect(sql).toContain("drop constraint if exists slate_cache_audit_subject_kind_check");
    expect(sql).toContain(
      "check (subject_kind in ('preset', 'rule', 'purge', 'trace', 'cdn'))",
    );
  });

  it("leaves V187's dispatch guard in place", () => {
    expect(sql).not.toMatch(/drop constraint[^;]*slate_cache_purges_dispatch_needs_edge/);
    expect(sql).not.toMatch(/alter table apiome\.slate_cache_purges/);
  });

  it("documents every column of both new tables", () => {
    for (const table of ["slate_cdn_providers", "slate_cdn_purge_dispatches"]) {
      const block = sql.split(`create table if not exists apiome.${table} (`)[1].split("\n);")[0];
      const columns = block
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => /^[a-z_]+\s+(uuid|text|bytea|integer|boolean|timestamp)/.test(line))
        .map((line) => line.split(/\s+/)[0])
        .filter((name) => name !== "id");
      for (const column of columns) {
        expect(sql).toContain(`comment on column apiome.${table}.${column} is`);
      }
    }
  });
});
