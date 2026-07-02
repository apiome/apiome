/**
 * Structural assertions over the MCP scores / discovery-jobs / test-invocations migration
 * (#3655, V2-MCP-15.5).
 *
 * V130 adds three tables: `apiome.mcp_version_scores` (one quality score per discovery snapshot),
 * `apiome.mcp_discovery_jobs` (the async discovery work log), and `apiome.mcp_test_invocations` (the
 * test-console call log). The acceptance criteria are that all three exist with the right indexes
 * (`(endpoint_id, created_at)` and `(state)`) and that the foreign keys cascade on endpoint delete.
 * These tests verify the migration's shape — tables, columns, constraints, FK cascades, and indexes —
 * without a live database (this package's suite is DB-free; the SQL is asserted structurally, and
 * end-to-end application is proven elsewhere).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V130__mcp_catalog_scores_jobs_invocations_3655.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP scores / discovery-jobs / test-invocations migration", () => {
  it("is present in scripts/ and ordered after V129", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V129__mcp_catalog_credential_vault_3654.sql"),
    );
  });

  it("creates all three tables idempotently in the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_version_scores/);
    expect(lower).toMatch(/create table if not exists mcp_discovery_jobs/);
    expect(lower).toMatch(/create table if not exists mcp_test_invocations/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  // --- mcp_version_scores --------------------------------------------------------------------------

  describe("mcp_version_scores", () => {
    it("defines every column from the ticket's field set", () => {
      for (const col of [
        "id",
        "version_id",
        "score",
        "grade",
        "report",
        "report_fingerprint",
        "scored_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("keys to a version snapshot and cascades on version (hence endpoint) delete", () => {
      expect(lower).toMatch(
        /version_id uuid not null references mcp_endpoint_versions\(id\) on delete cascade/,
      );
    });

    it("mirrors versions.quality_* types (score SMALLINT, grade TEXT, report_fingerprint TEXT)", () => {
      expect(sql).toMatch(/score SMALLINT/);
      expect(sql).toMatch(/grade TEXT/);
      expect(sql).toMatch(/report_fingerprint TEXT/);
      expect(sql).toMatch(/report JSONB/);
    });

    it("enforces one score per version via a UNIQUE constraint", () => {
      expect(lower).toMatch(/unique\s*\(version_id\)/);
    });

    it("constrains score to the 0-100 range", () => {
      expect(lower).toMatch(/score >= 0 and score <= 100/);
    });

    it("documents the table and all of its columns", () => {
      expect(lower).toMatch(/comment on table mcp_version_scores is/);
      const columnComments = (sql.match(/COMMENT ON COLUMN mcp_version_scores\./g) ?? []).length;
      // 8 columns: id, version_id, score, grade, report, report_fingerprint, scored_at, created_at.
      expect(columnComments).toBe(8);
    });
  });

  // --- mcp_discovery_jobs --------------------------------------------------------------------------

  describe("mcp_discovery_jobs", () => {
    it("defines every column from the ticket's field set", () => {
      for (const col of [
        "id",
        "endpoint_id",
        "tenant_id",
        "state",
        "trigger",
        "started_at",
        "finished_at",
        "error",
        "result",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("cascades on endpoint delete and on tenant delete", () => {
      expect(lower).toMatch(
        /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
      );
      expect(lower).toMatch(
        /tenant_id uuid not null references tenants\(id\) on delete cascade/,
      );
    });

    it("constrains state to the four lifecycle values", () => {
      expect(lower).toMatch(/check\s*\(state in \(/);
      for (const s of ["'queued'", "'running'", "'completed'", "'failed'"]) {
        expect(sql).toContain(s);
      }
    });

    it("constrains trigger to the three enqueue sources", () => {
      expect(lower).toMatch(/check\s*\(trigger in \(/);
      for (const t of ["'manual'", "'sweep'", "'registry'"]) {
        expect(sql).toContain(t);
      }
    });

    it("indexes (state) for the scheduler", () => {
      expect(lower).toMatch(/create index if not exists \S+\s+on mcp_discovery_jobs\(state\)/);
    });

    it("indexes (endpoint_id, created_at) for the per-endpoint job log", () => {
      expect(lower).toMatch(
        /on mcp_discovery_jobs\(endpoint_id, created_at desc\)/,
      );
    });

    it("documents the table and all of its columns", () => {
      expect(lower).toMatch(/comment on table mcp_discovery_jobs is/);
      const columnComments = (sql.match(/COMMENT ON COLUMN mcp_discovery_jobs\./g) ?? []).length;
      // 10 columns: id, endpoint_id, tenant_id, state, trigger, started_at, finished_at, error,
      // result, created_at.
      expect(columnComments).toBe(10);
    });
  });

  // --- mcp_test_invocations ------------------------------------------------------------------------

  describe("mcp_test_invocations", () => {
    it("defines every column from the ticket's field set", () => {
      for (const col of [
        "id",
        "endpoint_id",
        "version_id",
        "item_type",
        "item_name",
        "arguments",
        "response",
        "is_error",
        "latency_ms",
        "invoked_by",
        "created_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("cascades on endpoint delete", () => {
      expect(lower).toMatch(
        /endpoint_id uuid not null references mcp_endpoints\(id\) on delete cascade/,
      );
    });

    it("references a version with SET NULL so the log survives version pruning", () => {
      expect(lower).toMatch(
        /version_id uuid references mcp_endpoint_versions\(id\) on delete set null/,
      );
    });

    it("references the invoking user with SET NULL so the log survives user removal", () => {
      expect(lower).toMatch(/invoked_by uuid references users\(id\) on delete set null/);
    });

    it("constrains item_type to the four MCP capability kinds", () => {
      expect(lower).toMatch(/check\s*\(item_type in \(/);
      for (const k of ["'tool'", "'resource'", "'resource_template'", "'prompt'"]) {
        expect(sql).toContain(k);
      }
    });

    it("types is_error as BOOLEAN and latency_ms as INTEGER with a non-negative check", () => {
      expect(sql).toMatch(/is_error BOOLEAN NOT NULL DEFAULT false/);
      expect(sql).toMatch(/latency_ms INTEGER/);
      expect(lower).toMatch(/latency_ms is null or latency_ms >= 0/);
    });

    it("indexes (endpoint_id, created_at) for the per-endpoint invocation log", () => {
      expect(lower).toMatch(
        /on mcp_test_invocations\(endpoint_id, created_at desc\)/,
      );
    });

    it("documents the table and all of its columns", () => {
      expect(lower).toMatch(/comment on table mcp_test_invocations is/);
      const columnComments = (sql.match(/COMMENT ON COLUMN mcp_test_invocations\./g) ?? []).length;
      // 11 columns: id, endpoint_id, version_id, item_type, item_name, arguments, response,
      // is_error, latency_ms, invoked_by, created_at.
      expect(columnComments).toBe(11);
    });
  });
});
