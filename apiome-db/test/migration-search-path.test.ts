/**
 * Every migration that names an extension object without a schema sets its own search path.
 *
 * `pg_trgm` and `uuid-ossp` live in the `apiome` schema. The migrator runs all pending scripts on
 * one connection, so on a fresh database a `SET search_path TO apiome, public` from an earlier
 * script is still in effect, and a script that leans on it passes. On a database upgraded later,
 * the run starts on a new connection with the default path and the same script fails
 * (V424: `operator class "gin_trgm_ops" does not exist for access method "gin"`). This test reads
 * the scripts, so it catches that without a database.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { computeChecksum, isSupersededChecksum, SUPERSEDED_CHECKSUMS } from "../src/migrate.js";

const SCRIPTS_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "scripts");

/** Unqualified uses of objects that `pg_trgm` or `uuid-ossp` create in the `apiome` schema. */
const EXTENSION_OBJECT = /\b(?:gin|gist)_trgm_ops\b|\buuid_generate_v[14]\s*\(|\b(?:strict_word_|word_)?similarity\s*\(/i;

/** A statement that sets the search path for the rest of the script. */
const SETS_SEARCH_PATH = /\bset\s+(?:local\s+)?search_path\b|set_config\s*\(\s*'search_path'/i;

/**
 * Scripts applied everywhere before this test existed that rely on an earlier script's path.
 * They are never run on an upgraded database any more, so they are left as they are.
 */
const ALLOWED = new Set<string>([
  // uuid_generate_v4() with V184's path; every supported database is past V185.
  "V185__source_change_audit_2360.sql",
]);

/**
 * Remove `--` line comments, so that comments naming an object do not count as uses of it.
 *
 * @param sql - Script text.
 * @returns The text with every `--` comment removed up to its line end.
 */
function stripLineComments(sql: string): string {
  return sql.replace(/--[^\n]*/g, "");
}

/**
 * Find where a script first uses an extension object and first sets the search path.
 *
 * @param sql - Script text.
 * @returns Character offsets of both, or -1 for one that does not occur.
 */
function searchPathOrder(sql: string): { use: number; set: number } {
  const body = stripLineComments(sql);
  return { use: body.search(EXTENSION_OBJECT), set: body.search(SETS_SEARCH_PATH) };
}

describe("searchPathOrder", () => {
  it("finds a use after the search path is set", () => {
    const sql = "SET search_path TO apiome, public;\nCREATE INDEX i ON t USING gin (c gin_trgm_ops);";
    const { use, set } = searchPathOrder(sql);
    expect(set).toBeGreaterThanOrEqual(0);
    expect(use).toBeGreaterThan(set);
  });

  it("reports a use with no search path", () => {
    expect(searchPathOrder("CREATE INDEX i ON t USING gin (c gin_trgm_ops);").set).toBe(-1);
  });

  it("ignores objects named only in comments", () => {
    expect(searchPathOrder("-- gin_trgm_ops resolves through the search path\nSELECT 1;").use).toBe(-1);
  });
});

describe("migration scripts", () => {
  const files = fs.readdirSync(SCRIPTS_DIR).filter((f) => /^V\d.*__.*\.sql$/.test(f)).sort();

  it("set their own search path before naming an extension object", () => {
    const offenders = files.filter((file) => {
      if (ALLOWED.has(file)) return false;
      const { use, set } = searchPathOrder(fs.readFileSync(path.join(SCRIPTS_DIR, file), "utf8"));
      return use >= 0 && (set < 0 || set > use);
    });
    expect(offenders).toEqual([]);
  });

  it("list superseded checksums only for scripts that exist and have changed since", () => {
    for (const [file, checksums] of Object.entries(SUPERSEDED_CHECKSUMS)) {
      const current = computeChecksum(fs.readFileSync(path.join(SCRIPTS_DIR, file), "utf8"));
      expect(checksums).not.toContain(current);
      for (const checksum of checksums) expect(isSupersededChecksum(file, checksum)).toBe(true);
    }
  });

  it("accept no checksum for a script that is not listed", () => {
    expect(isSupersededChecksum("V001__multitenant_init.sql", -1622066416)).toBe(false);
  });
});
