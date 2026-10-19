/**
 * Structural assertions over the `registry:read` / `registry:write` scope migration (CDG-4.3, #5975).
 *
 * V295 widens the `api_keys.scopes` vocabulary by the two schema registry scopes and restates the
 * V269 rule that pins an agent key to exactly `agent:invoke`. Runtime allowlist enforcement lives in
 * apiome-rest auth. DB-free contract tests pin the migration shape and the CLI vocabulary.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { API_KEY_SCOPE_VOCAB, normalizeApiKeyScopes } from "../src/commands/apikeys.js";
import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V295__registry_scopes_cdg_4_3.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("registry scopes migration (CDG-4.3)", () => {
  it("is present in scripts/ and ordered after V294", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V294__schema_subjects_cdg_4_2.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("widens the vocabulary by both registry scopes, keeping every earlier scope", () => {
    expect(lower).toMatch(
      /scopes\s*<@\s*array\[\s*'\*',\s*'diff:read',\s*'lint:read',\s*'agent:invoke',\s*'usage:ingest',\s*'registry:read',\s*'registry:write'\s*\]/,
    );
  });

  it("keeps agent keys pinned to agent:invoke alone", () => {
    expect(lower).toMatch(/kind = 'agent' and scopes = array\['agent:invoke'\]::text\[\]/);
  });

  it("documents the scopes and the rollback", () => {
    expect(lower).toMatch(/comment on column api_keys\.scopes is/);
    expect(sql).toMatch(/CDG-4\.3/);
    expect(lower).toContain("rollback notes");
  });
});

describe("apikeys CLI vocabulary", () => {
  it("accepts the registry scopes alone and together", () => {
    expect(API_KEY_SCOPE_VOCAB.has("registry:read")).toBe(true);
    expect(API_KEY_SCOPE_VOCAB.has("registry:write")).toBe(true);
    expect(normalizeApiKeyScopes("registry:read")).toEqual(["registry:read"]);
    expect(normalizeApiKeyScopes("registry:read,registry:write")).toEqual([
      "registry:read",
      "registry:write",
    ]);
  });

  it("still refuses * beside a registry scope", () => {
    expect(() => normalizeApiKeyScopes("*,registry:read")).toThrow(/must stand alone/);
  });
});
