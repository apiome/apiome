/**
 * Structural assertions over the consumer-tagged mock capture migration (#7319, PFX-9.1).
 *
 * V461 stores calls to the hosted mock recorded for a consumer and version:
 *
 *   1. It sets its own search path first and comes after the set-up progress migration.
 *   2. Every table carries its tenant and goes with it; sessions and calls go with their version.
 *   3. Retention is bounded (1–30 days, default 7) and every session and call has `expires_at`.
 *   4. A capture link stores only the token's digest, never the token.
 *   5. A call's origin is one of the known values; one session per version, consumer and version.
 *   6. Every new foreign key is indexed, and expiry is indexed for the sweeper.
 *
 * `apiome-rest/tests/test_pact_capture_db.py` proves the same rules against a migrated database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V461__mock_consumer_capture_7319.sql";

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** The body of one `CREATE TABLE` statement. */
function tableOf(ddl: string, name: string): string {
  const start = ddl.indexOf(`create table if not exists ${name} (`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(");", start));
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("mock consumer capture migration (PFX-9.1)", () => {
  it("is present in scripts/ and ordered after the set-up progress migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V460__pact_setup_progress_7317.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it("removes every table's rows with the tenant", () => {
    for (const table of [
      "mock_consumer_capture_settings",
      "mock_consumer_capture_link",
      "mock_consumer_capture_session",
      "mock_consumer_capture_call",
    ]) {
      expect(tableOf(ddl, table)).toContain("references tenants(id) on delete cascade");
    }
  });

  it("removes links and sessions with their version, and calls with their session", () => {
    expect(tableOf(ddl, "mock_consumer_capture_link")).toContain("version_id uuid not null references versions(id) on delete cascade");
    expect(tableOf(ddl, "mock_consumer_capture_session")).toContain("version_id uuid not null references versions(id) on delete cascade");
    expect(tableOf(ddl, "mock_consumer_capture_call")).toContain(
      "session_id uuid not null references mock_consumer_capture_session(id) on delete cascade",
    );
  });

  it("bounds retention and gives every session and call an expiry", () => {
    expect(ddl).toContain("retention_days integer not null default 7");
    expect(ddl).toContain("check (retention_days between 1 and 30)");
    expect(tableOf(ddl, "mock_consumer_capture_session")).toContain("expires_at timestamp with time zone not null");
    expect(tableOf(ddl, "mock_consumer_capture_call")).toContain("expires_at timestamp with time zone not null");
  });

  it("stores a link's token digest and never the token", () => {
    const link = tableOf(ddl, "mock_consumer_capture_link");
    expect(link).toContain("check (token_hash ~ '^[0-9a-f]{64}$')");
    expect(link).toContain("unique (token_hash)");
    expect(link).not.toMatch(/\btoken text\b/);
  });

  it("knows every origin and keeps one session per version, consumer and consumer version", () => {
    expect(ddl).toContain(
      "check (origin in ('spec', 'scenario', 'session', 'chaos', 'forced', 'off-spec', 'rejected'))",
    );
    expect(ddl).toContain("unique (version_id, consumer, consumer_version)");
  });

  it("indexes every new foreign key and the expiry columns", () => {
    for (const index of [
      "on mock_consumer_capture_settings (updated_by) where updated_by is not null",
      "on mock_consumer_capture_link (tenant_id, created_at desc)",
      "on mock_consumer_capture_link (version_id)",
      "on mock_consumer_capture_link (created_by) where created_by is not null",
      "on mock_consumer_capture_session (tenant_id, last_call_at desc)",
      "on mock_consumer_capture_session (expires_at)",
      "on mock_consumer_capture_call (session_id, id)",
      "on mock_consumer_capture_call (tenant_id)",
      "on mock_consumer_capture_call (expires_at)",
      "on mock_consumer_capture_call (link_id) where link_id is not null",
      "on mock_consumer_capture_call (api_key_id) where api_key_id is not null",
    ]) {
      expect(ddl).toContain(index);
    }
  });
});
