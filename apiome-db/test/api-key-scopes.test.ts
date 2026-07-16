/**
 * Structural assertions over the API key scopes migration (#4473, CTG-2.3).
 *
 * V177 extends `apiome.api_keys` with `scopes TEXT[]` (default `['*']`) and
 * CHECKs (non-empty, vocab, `*` alone). Runtime allowlist enforcement lives in
 * apiome-rest auth.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V177__api_key_scopes_4473.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("API key scopes migration (CTG-2.3)", () => {
  it("is present in scripts/ and ordered after V176", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V176__lint_ci_gate_4860.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("extends api_keys rather than creating a child table", () => {
    expect(lower).toMatch(/alter table api_keys/);
    expect(lower).not.toMatch(/create table.*api_key_scopes/);
  });

  it("documents rollback drops", () => {
    expect(lower).toContain("drop constraint if exists api_keys_scopes_vocab_ck");
    expect(lower).toContain("drop constraint if exists api_keys_scopes_star_alone_ck");
    expect(lower).toContain("drop constraint if exists api_keys_scopes_nonempty_ck");
    expect(lower).toContain("drop column if exists scopes");
  });

  describe("columns and defaults", () => {
    it("adds scopes text[] defaulting to ['*']", () => {
      expect(lower).toMatch(
        /scopes\s+text\[\]\s+not null\s+default\s+array\['\*'\]/,
      );
    });

    it("requires a non-empty scopes array", () => {
      expect(lower).toMatch(
        /api_keys_scopes_nonempty_ck[\s\S]*?check \(cardinality\(scopes\) >= 1\)/,
      );
    });

    it("constrains scopes to *, diff:read, lint:read", () => {
      expect(lower).toMatch(/api_keys_scopes_vocab_ck/);
      expect(sql).toMatch(/diff:read/);
      expect(sql).toMatch(/lint:read/);
      expect(lower).toMatch(/scopes\s*<@\s*array\['\*',\s*'diff:read',\s*'lint:read'\]/);
    });

    it("requires * to stand alone when present", () => {
      expect(lower).toMatch(
        /api_keys_scopes_star_alone_ck[\s\S]*?not\s*\('\*'\s*=\s*any\s*\(scopes\)\)\s*or\s*cardinality\(scopes\)\s*=\s*1/,
      );
    });

    it("documents the scopes column", () => {
      expect(lower).toMatch(/comment on column api_keys\.scopes is/);
      expect(sql).toMatch(/CTG-2\.3/);
      expect(sql).toMatch(/#4473/);
    });
  });
});
