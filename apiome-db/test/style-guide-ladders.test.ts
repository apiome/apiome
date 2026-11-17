/**
 * Structural assertions over the maturity-ladder migration (GVM-1.1, #5854).
 *
 * V390 adds `style_guide_ladders` (one ladder per guide), freezes a nullable `ladder` into
 * style-guide revisions and policy packs, and adds the `ladder_changed` revision kind.
 * DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V390__style_guide_ladders_gvm_1_1.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("Style-guide ladders migration (GVM-1.1)", () => {
  it("is present in scripts/ and ordered after V389", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V389__api_lifecycle_apx_1_4.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates one ladder per guide with an array of levels", () => {
    expect(lower).toContain("create table if not exists style_guide_ladders");
    expect(lower).toContain("guide_id uuid not null unique references style_guides(id) on delete cascade");
    expect(lower).toContain("levels jsonb not null");
    expect(lower).toContain("content_fingerprint text not null");
    expect(lower).toContain("check (jsonb_typeof(levels) = 'array')");
  });

  it("freezes a nullable ladder into revisions and policy packs", () => {
    expect(lower).toMatch(/alter table style_guide_revisions\s+add column if not exists ladder jsonb;/);
    expect(lower).toMatch(/alter table style_guide_policy_versions\s+add column if not exists ladder jsonb;/);
  });

  it("adds ladder_changed to the revision change kinds", () => {
    expect(lower).toContain("drop constraint if exists style_guide_revisions_change_kind_check");
    expect(lower).toMatch(/'imported',\s+'ladder_changed'\)/);
  });

  it("seeds no ladder for any tenant", () => {
    expect(lower).not.toContain("insert into");
  });
});
