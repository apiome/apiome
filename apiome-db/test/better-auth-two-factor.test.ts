/**
 * Structural assertions over the Better Auth 2FA-foundation migration (#5005, OLO-10.10).
 *
 * V201 stands up the persistence the Better Auth `twoFactor` plugin needs: a new `apiome.two_factor`
 * table (mapped from the plugin's `twoFactor` model) and a `"twoFactorEnabled"` flag on the reused
 * `users` table. See docs/BETTER_AUTH_MIGRATION.md §2.5 / §2.1.
 *
 * These are DB-free contract tests: they read the migration text and pin the shape the twoFactor
 * plugin reads (the snake_case table name with the plugin's native quoted camelCase columns, the
 * UUID FK onto users, the plugin defaults, additivity/idempotency/reversibility) so a later edit
 * cannot silently drift the schema away from what the plugin (apiome-ui/lib/auth/auth.ts,
 * `twoFactor({ twoFactorTable: 'two_factor' })`, no field mapping) expects.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V201__better_auth_two_factor_5005.sql";

let sql = "";
let lower = "";
// Executable SQL only (comment lines stripped) — the header comment documents the rollback, which
// legitimately mentions DROP TABLE / DELETE; the destructive-DDL checks must inspect only the DDL
// that actually runs.
let code = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  code = lower
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
});

describe("Better Auth 2FA-foundation migration", () => {
  it("is present and ordered after the credential-relocation migration (V200)", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V200__better_auth_credential_password_relocation_5000.sql"),
    );
  });

  it("targets the apiome schema (search_path preserved)", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the two_factor table, guarded (IF NOT EXISTS)", () => {
    expect(lower).toMatch(/create table if not exists apiome\.two_factor\b/);
  });

  it("uses the plugin's native quoted camelCase columns (not snake_case)", () => {
    for (const col of [
      '"userId"',
      '"secret"',
      '"backupCodes"',
      '"verified"',
      '"failedVerificationCount"',
      '"lockedUntil"',
    ]) {
      expect(sql).toContain(col);
    }
  });

  it("makes the id TEXT (plugin-generated) and userId a UUID FK onto users (ON DELETE CASCADE)", () => {
    expect(lower).toMatch(/"id"\s+text primary key/);
    expect(lower).toMatch(
      /"userid"\s+uuid not null references apiome\.users\(id\) on delete cascade/,
    );
  });

  it("requires the encrypted secret and backup codes (NOT NULL)", () => {
    expect(lower).toMatch(/"secret"\s+text not null/);
    expect(lower).toMatch(/"backupcodes"\s+text not null/);
  });

  it("carries the plugin's field defaults (verified=true, failedVerificationCount=0)", () => {
    expect(lower).toMatch(/"verified"\s+boolean not null default true/);
    expect(lower).toMatch(/"failedverificationcount"\s+integer not null default 0/);
  });

  it("stores the lockout expiry as a nullable timestamptz", () => {
    // No NOT NULL / DEFAULT on lockedUntil — NULL means "not locked" (§2.5).
    expect(lower).toMatch(/"lockeduntil"\s+timestamptz(?!\s+not null)/);
  });

  it("indexes the plugin's index:true fields (userId, secret)", () => {
    expect(lower).toMatch(/create index if not exists .*on apiome\.two_factor \("userid"\)/);
    expect(lower).toMatch(/create index if not exists .*on apiome\.two_factor \("secret"\)/);
  });

  it("adds the user flag as a native quoted camelCase column, idempotently, default false", () => {
    expect(lower).toMatch(
      /alter table\s+apiome\.users\s+add column if not exists "twofactorenabled" boolean not null default false/,
    );
  });

  it("is additive / reversible — creates only, drops or rewrites nothing (§4 rollback)", () => {
    // No destructive DDL and no data rewrite of the reused user table (executable SQL only).
    expect(code).not.toMatch(/drop table/);
    expect(code).not.toMatch(/update\s+(apiome\.)?users\b/);
    expect(code).not.toMatch(/delete\s+from/);
    // The only ALTER is the additive ADD COLUMN (no DROP/rewrite of existing user columns).
    expect(code).not.toMatch(/alter table[^\n]*\bdrop\b/);
    // No password/secret backfill — 2FA is opt-in, every existing user starts disabled with no row.
    expect(code).not.toContain("insert into apiome.two_factor");
  });

  it("does not store the TOTP secret in plaintext (encrypted at rest — R11)", () => {
    // The plugin encrypts secret/backupCodes before insert; the migration must not add crypto of its own.
    expect(code).not.toContain("crypt(");
    expect(code).not.toContain("gen_salt");
  });
});
