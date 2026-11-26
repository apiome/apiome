/**
 * Structural assertions over the `pact:read` / `pact:publish` / `pact:verify` scope migration
 * (PFX-4.2, #6939).
 *
 * V442 widens the `api_keys.scopes` vocabulary by the three Pact Broker scopes and restates the
 * V269 rule that pins an agent key to exactly `agent:invoke`. Runtime allowlist enforcement lives
 * in apiome-rest auth. DB-free contract tests pin the migration shape and the CLI vocabulary.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { API_KEY_SCOPE_VOCAB, normalizeApiKeyScopes } from "../src/commands/apikeys.js";
import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V442__pact_scopes_6939.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("pact scopes migration (PFX-4.2)", () => {
  it("is present in scripts/ and ordered after V441", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V441__pact_provider_states_6933.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("widens the vocabulary by the three pact scopes, keeping every earlier scope", () => {
    expect(lower).toMatch(
      /scopes\s*<@\s*array\[\s*'\*',\s*'diff:read',\s*'lint:read',\s*'agent:invoke',\s*'usage:ingest',\s*'registry:read',\s*'registry:write',\s*'pact:read',\s*'pact:publish',\s*'pact:verify'\s*\]/,
    );
  });

  it("keeps agent keys pinned to agent:invoke alone", () => {
    expect(lower).toMatch(/kind = 'agent' and scopes = array\['agent:invoke'\]::text\[\]/);
  });

  it("documents the scopes and the rollback", () => {
    expect(lower).toMatch(/comment on column api_keys\.scopes is/);
    expect(sql).toMatch(/PFX-4\.2/);
    expect(lower).toContain("rollback notes");
  });
});

describe("apikeys CLI vocabulary", () => {
  it("accepts each pact scope alone and the CI pairs", () => {
    for (const scope of ["pact:read", "pact:publish", "pact:verify"]) {
      expect(API_KEY_SCOPE_VOCAB.has(scope)).toBe(true);
      expect(normalizeApiKeyScopes(scope)).toEqual([scope]);
    }
    expect(normalizeApiKeyScopes("pact:read,pact:verify")).toEqual(["pact:read", "pact:verify"]);
    expect(normalizeApiKeyScopes("pact:read,pact:publish")).toEqual(["pact:read", "pact:publish"]);
  });

  it("refuses an unknown pact scope and names the allowed ones", () => {
    expect(() => normalizeApiKeyScopes("pact:write")).toThrow(/Invalid API key scope "pact:write"/);
    expect(() => normalizeApiKeyScopes("pact:write")).toThrow(/pact:verify/);
  });

  it("still refuses * beside a pact scope", () => {
    expect(() => normalizeApiKeyScopes("*,pact:read")).toThrow(/must stand alone/);
  });
});
