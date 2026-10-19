/**
 * Structural assertions over the `usage:ingest` scope migration (RDG-1.2, #5760).
 *
 * V291 widens the `api_keys.scopes` vocabulary by `usage:ingest` and restates the V269 rule that
 * pins an agent key to exactly `agent:invoke`, so the usage ingest route can only be reached with
 * a workspace key. Runtime allowlist enforcement lives in apiome-rest auth.
 *
 * DB-free contract tests pin the migration shape and the CLI vocabulary.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { API_KEY_SCOPE_VOCAB, normalizeApiKeyScopes } from "../src/commands/apikeys.js";
import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V291__usage_ingest_scope_rdg_1_2.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("usage:ingest scope migration (RDG-1.2)", () => {
  it("is present in scripts/ and ordered after V290", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V290__usage_index_rdg_1_1.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("widens the vocabulary by usage:ingest, keeping every earlier scope", () => {
    expect(lower).toMatch(
      /scopes\s*<@\s*array\['\*',\s*'diff:read',\s*'lint:read',\s*'agent:invoke',\s*'usage:ingest'\]/,
    );
  });

  it("keeps agent keys pinned to agent:invoke alone", () => {
    expect(lower).toMatch(
      /kind = 'agent' and scopes = array\['agent:invoke'\]::text\[\]/,
    );
  });

  it("documents the scope and the rollback", () => {
    expect(lower).toMatch(/comment on column api_keys\.scopes is/);
    expect(sql).toMatch(/RDG-1\.2/);
    expect(lower).toContain("rollback notes");
  });
});

describe("apikeys CLI vocabulary", () => {
  it("accepts usage:ingest on its own and beside the CI scopes", () => {
    expect(API_KEY_SCOPE_VOCAB.has("usage:ingest")).toBe(true);
    expect(normalizeApiKeyScopes("usage:ingest")).toEqual(["usage:ingest"]);
    expect(normalizeApiKeyScopes("usage:ingest,lint:read")).toEqual([
      "usage:ingest",
      "lint:read",
    ]);
  });

  it("still refuses agent:invoke and * beside another scope", () => {
    expect(() => normalizeApiKeyScopes("agent:invoke")).toThrow(/Invalid API key scope/);
    expect(() => normalizeApiKeyScopes("*,usage:ingest")).toThrow(/must stand alone/);
  });
});
