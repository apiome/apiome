/**
 * Structural assertions over the approval-policy migration (#4519, COL-2.3).
 *
 * V262 adds `apiome.style_guides.required_approvals` and
 * `apiome.style_guides.required_reviewer_role` — the tenant governance setting the publish
 * flow reads through the GOV-1.4 guide chain to decide whether a draft has collected enough
 * review approvals to ship. The gate itself lives in apiome-rest (Python); this SQL only has
 * to be additive, defaulted to "off", and bounded.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V262__approval_publish_policy_col_2_3.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("approval policy migration (COL-2.3)", () => {
  it("is present in scripts/ and ordered after the review tables", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V261__review_requests_4517.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("documents the rollback for both columns", () => {
    expect(lower).toContain(
      "alter table apiome.style_guides drop column if exists required_approvals",
    );
    expect(lower).toContain(
      "alter table apiome.style_guides drop column if exists required_reviewer_role",
    );
  });

  describe("columns", () => {
    it("adds them to style_guides, not a new table", () => {
      expect(lower).toMatch(
        /alter table apiome\.style_guides\s+add column if not exists required_approvals integer not null default 0/,
      );
      expect(lower).toMatch(
        /alter table apiome\.style_guides\s+add column if not exists required_reviewer_role varchar\(64\)/,
      );
      expect(lower).not.toMatch(/create table/);
    });

    it("defaults the gate off so existing guides keep publishing as before", () => {
      expect(lower).toContain("default 0");
    });

    it("leaves the required reviewer role nullable — any approver counts by default", () => {
      expect(lower).not.toMatch(/required_reviewer_role varchar\(64\) not null/);
    });

    it("documents both columns with comments naming the ticket", () => {
      expect(lower).toContain("comment on column style_guides.required_approvals");
      expect(lower).toContain("comment on column style_guides.required_reviewer_role");
      expect(sql.match(/COL-2\.3, #4519/g)?.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe("constraints", () => {
    it("bounds required approvals by the reviewer cap so the gate stays satisfiable", () => {
      expect(lower).toMatch(
        /check \(required_approvals >= 0 and required_approvals <= 20\)/,
      );
    });

    it("rejects a blank required reviewer role", () => {
      expect(lower).toContain("char_length(btrim(required_reviewer_role))");
    });

    it("guards both so re-running the migration is a no-op", () => {
      expect(lower).toContain("style_guides_required_approvals_ck");
      expect(lower).toContain("style_guides_required_reviewer_role_ck");
      expect(lower.match(/if not exists \(\s*select 1\s*from pg_constraint/g)).toHaveLength(2);
    });
  });
});
