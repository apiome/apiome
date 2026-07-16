/**
 * Structural assertions over the version_changelogs migration (#4475, CTG-3.1).
 *
 * V178 creates `apiome.version_changelogs` (one row per published revision) with
 * jsonb changelog, denormalized max_severity, and status ready|initial|failed.
 * Classification/backfill run in apiome-rest (Python), not in this SQL.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V178__version_changelogs_4475.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("version_changelogs migration (CTG-3.1)", () => {
  it("is present in scripts/ and ordered after V177", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V177__api_key_scopes_4473.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates version_changelogs (not a child-per-change table)", () => {
    expect(lower).toMatch(/create table if not exists version_changelogs/);
    expect(lower).not.toMatch(/create table.*version_changelog_entries/);
  });

  it("documents rollback drop", () => {
    expect(lower).toContain("drop table if exists apiome.version_changelogs cascade");
  });

  it("documents post-migrate Python backfill", () => {
    expect(sql).toMatch(/backfill_version_changelogs/);
  });

  describe("columns and constraints", () => {
    it("has unique published_revision_id", () => {
      expect(lower).toMatch(
        /version_changelogs_published_revision_unique\s+unique\s*\(\s*published_revision_id\s*\)/,
      );
    });

    it("FKs tenant, project, published revision, nullable baseline", () => {
      expect(lower).toMatch(/tenant_id\s+uuid not null references tenants/);
      expect(lower).toMatch(/project_id\s+uuid not null references projects/);
      expect(lower).toMatch(
        /published_revision_id\s+uuid not null references versions/,
      );
      expect(lower).toMatch(
        /baseline_revision_id\s+uuid references versions\(id\) on delete set null/,
      );
    });

    it("constrains status to ready | initial | failed", () => {
      expect(lower).toMatch(
        /version_changelogs_status_ck[\s\S]*?check \(status in \('ready', 'initial', 'failed'\)\)/,
      );
    });

    it("constrains max_severity vocabulary", () => {
      expect(lower).toMatch(/version_changelogs_max_severity_ck/);
      expect(sql).toMatch(/'breaking'/);
      expect(sql).toMatch(/'non-breaking'/);
      expect(sql).toMatch(/'docs-only'/);
    });

    it("indexes tenant/project and project/max_severity", () => {
      expect(lower).toMatch(
        /idx_version_changelogs_tenant_project[\s\S]*?on version_changelogs\s*\(\s*tenant_id,\s*project_id\s*\)/,
      );
      expect(lower).toMatch(
        /idx_version_changelogs_project_max_severity[\s\S]*?on version_changelogs\s*\(\s*project_id,\s*max_severity\s*\)/,
      );
    });

    it("documents table and key columns", () => {
      expect(lower).toMatch(/comment on table version_changelogs is/);
      expect(lower).toMatch(/comment on column version_changelogs\.changelog_json is/);
      expect(lower).toMatch(/comment on column version_changelogs\.max_severity is/);
      expect(sql).toMatch(/CTG-3\.1/);
      expect(sql).toMatch(/#4475/);
    });
  });
});
