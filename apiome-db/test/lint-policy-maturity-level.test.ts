/**
 * Structural assertions over the maturity-level migration (GVM-1.2, #5855).
 *
 * V391 adds `lint_policy_evaluations.maturity_level` and an index for level aggregation.
 * DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V391__lint_policy_maturity_level_gvm_1_2.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("Lint policy maturity-level migration (GVM-1.2)", () => {
  it("is present in scripts/ and ordered after V390", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V390__style_guide_ladders_gvm_1_1.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds a nullable maturity_level column", () => {
    expect(lower).toMatch(/alter table lint_policy_evaluations\s+add column if not exists maturity_level text;/);
  });

  it("indexes the level for aggregation", () => {
    expect(lower).toContain("create index if not exists idx_lint_policy_evaluations_maturity_level");
    expect(lower).toContain("on lint_policy_evaluations (maturity_level, evaluated_at desc)");
    expect(lower).toContain("where maturity_level is not null");
  });
});
