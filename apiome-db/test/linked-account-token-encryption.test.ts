/**
 * Structural assertions over the linked-account token encryption migration (#4960, OLO-7.3 follow-up).
 *
 * V275 accompanies the move to sealed provider tokens. A migration cannot encrypt — the master keys
 * live in the environment, out of the database's reach — so its contract is narrower and worth
 * pinning: it clears the plaintext token copies nothing reads, leaves `external_auth_providers` to
 * the application-side backfill, and corrects the "encrypted in production" comments that V010 and
 * V199 never made true. These tests verify that shape without a live database (this package's
 * suite is DB-free; the SQL is asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V275__encrypt_linked_account_tokens_4960.sql";

let sql = "";
/** The migration with `--` comment lines removed, so prose cannot satisfy a statement assertion. */
let statements = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
});

describe("linked-account token encryption migration", () => {
  it("is present in scripts/ and ordered after V274", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V274__signup_policy_sgn_1_4.sql"),
    );
  });

  it("clears Better Auth's unread token copies, sparing the credential rows", () => {
    const update = statements.match(/UPDATE apiome\.account[\s\S]*?;/)?.[0] ?? "";
    for (const column of ['"accessToken" = NULL', '"refreshToken" = NULL', '"idToken" = NULL']) {
      expect(update).toContain(column);
    }
    expect(update).toContain(`"providerId" <> 'credential'`);
    // The credential password hash lives in the same table and must never be touched.
    expect(update).not.toContain('"password"');
  });

  it("drops expired staged sign-ups and the plaintext tokens of live ones", () => {
    expect(statements).toMatch(
      /DELETE FROM apiome\.oauth_signup_pending\s+WHERE expires_at < CURRENT_TIMESTAMP;/,
    );
    expect(statements).toContain(
      "account_json = account_json - 'access_token' - 'refresh_token' - 'id_token'",
    );
  });

  it("leaves external_auth_providers rows for the application-side backfill", () => {
    // Sealing needs the environment's keys; nulling here would silently unlink every repository.
    expect(statements).not.toMatch(/UPDATE\s+(apiome\.)?external_auth_providers/i);
    expect(statements).not.toMatch(/DELETE\s+FROM\s+(apiome\.)?external_auth_providers/i);
    expect(sql).toContain("python -m app.seal_linked_account_tokens");
  });

  it("changes no table shape", () => {
    expect(statements).not.toMatch(/\b(ALTER|CREATE|DROP)\s+(TABLE|INDEX)\b/i);
  });

  it("replaces the 'encrypted in production' comments with the sealed form", () => {
    for (const column of [
      "apiome.external_auth_providers.access_token",
      "apiome.external_auth_providers.refresh_token",
      'apiome.account."accessToken"',
      'apiome.account."refreshToken"',
      'apiome.account."idToken"',
      "apiome.oauth_signup_pending.account_json",
    ]) {
      expect(statements).toContain(`COMMENT ON COLUMN ${column} IS`);
    }
    expect(statements).toContain("enc:v1:<key_version>:");
    expect(statements).not.toContain("should be encrypted");
  });
});
