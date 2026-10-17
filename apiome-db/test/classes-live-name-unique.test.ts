/**
 * Structural assertions over the live-class-name migration (#3231, CLI 7.3).
 *
 * V280 replaces `classes_version_name_unique` (every row) with a partial unique index over live
 * rows, so a soft-deleted class frees its name and `apiome classes create` can roll back a
 * half-made class and retry. DB-free contract tests; the SQL was run against Postgres 16 for the PR.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V280__classes_live_name_unique_3231.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("classes live-name uniqueness migration (#3231)", () => {
  it("is present in scripts/ and ordered after V279", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V279__version_spec_snapshots_3214.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("drops the all-rows constraint idempotently", () => {
    expect(lower).toContain("alter table apiome.classes drop constraint if exists classes_version_name_unique");
  });

  it("keeps live classes unique by version and name, ignoring soft-deleted ones", () => {
    expect(lower).toMatch(
      /create unique index if not exists classes_version_name_live_unique\s+on apiome\.classes \(version_id, name\)\s+where deleted_at is null/,
    );
  });

  it("documents the rollback", () => {
    expect(lower).toContain("drop index if exists apiome.classes_version_name_live_unique");
    expect(lower).toContain("add constraint classes_version_name_unique unique (version_id, name)");
  });
});
