/**
 * Structural assertions over the compatibility-mode policy migration (#5749, XPC-4.5).
 *
 * V382 adds three `apiome.style_guides` columns — the compatibility mode, whether it is
 * transitive, and the Protobuf buf breaking category — that the classified diff, the
 * compatibility check, the CI diff gate and the publish guardrail read through the GOV-1.4
 * guide chain. The grading itself lives in apiome-rest (Python); this SQL only has to be
 * additive, defaulted to today's grades, and constrained to the closed vocabularies.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V382__compatibility_mode_policy_xpc_4_5.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("compatibility-mode policy migration (XPC-4.5)", () => {
  it("is present in scripts/ and ordered after V381", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V381__index_hygiene_and_cascade_indexes.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("documents the rollback of every column", () => {
    for (const column of [
      "compatibility_mode",
      "compatibility_transitive",
      "protobuf_breaking_category",
    ]) {
      expect(lower).toContain(
        `alter table apiome.style_guides drop column if exists ${column}`,
      );
    }
  });

  describe("columns", () => {
    it("adds the mode to style_guides, defaulting to BACKWARD", () => {
      expect(lower).toMatch(
        /alter table apiome\.style_guides\s+add column if not exists compatibility_mode text not null default 'backward'/,
      );
      expect(lower).not.toMatch(/create table/);
    });

    it("adds transitivity, defaulting to false", () => {
      expect(lower).toMatch(
        /add column if not exists compatibility_transitive boolean not null default false/,
      );
    });

    it("adds the Protobuf category, defaulting to WIRE_JSON", () => {
      expect(lower).toMatch(
        /add column if not exists protobuf_breaking_category text not null default 'wire_json'/,
      );
    });

    it("documents each column with a comment naming the ticket", () => {
      expect(lower).toContain("comment on column style_guides.compatibility_mode");
      expect(lower).toContain("comment on column style_guides.compatibility_transitive");
      expect(lower).toContain("comment on column style_guides.protobuf_breaking_category");
      expect(sql.match(/XPC-4\.5, #5749/g)?.length).toBeGreaterThanOrEqual(3);
    });
  });

  describe("constraints", () => {
    it("restricts the mode to BACKWARD | FORWARD | FULL | NONE", () => {
      expect(sql).toMatch(
        /CHECK \(compatibility_mode IN \('BACKWARD', 'FORWARD', 'FULL', 'NONE'\)\)/,
      );
    });

    it("restricts the category to the four buf categories", () => {
      expect(sql).toMatch(
        /CHECK \(protobuf_breaking_category IN \('WIRE', 'WIRE_JSON', 'PACKAGE', 'FILE'\)\)/,
      );
    });

    it("is guarded so re-running the migration is a no-op", () => {
      expect(lower).toContain("style_guides_compatibility_mode_ck");
      expect(lower).toContain("style_guides_protobuf_breaking_category_ck");
      expect(lower).toMatch(/if not exists \(\s*select 1\s*from pg_constraint/);
    });
  });
});
