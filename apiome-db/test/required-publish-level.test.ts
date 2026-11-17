/**
 * Structural assertions over the required-publish-level migration (GVM-1.3, #5856).
 *
 * V392 adds `style_guides.required_publish_level` and freezes it into
 * `style_guide_policy_versions`. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V392__required_publish_level_gvm_1_3.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("Required publish level migration (GVM-1.3)", () => {
  it("is present in scripts/ and ordered after V391", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V391__lint_policy_maturity_level_gvm_1_2.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds a nullable required_publish_level to style_guides", () => {
    expect(lower).toMatch(/alter table style_guides\s+add column if not exists required_publish_level text;/);
  });

  it("freezes the level into policy packs", () => {
    expect(lower).toMatch(
      /alter table style_guide_policy_versions\s+add column if not exists required_publish_level text;/,
    );
  });

  it("adds no check constraint (the application validates the key against the ladder)", () => {
    expect(lower).not.toMatch(/add constraint[^;]*required_publish_level/);
  });
});
