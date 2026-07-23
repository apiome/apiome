/**
 * Structural assertions over the credential-password relocation migration (#5000, OLO-10.5).
 *
 * V200 relocates the credential password hashes off `apiome.users.password` into `apiome.account`
 * rows with `providerId='credential'` (the shape Better Auth's email/password sign-in reads). See
 * docs/BETTER_AUTH_MIGRATION.md §2.3 / §4.
 *
 * These are DB-free contract tests: they read the migration text and pin the load-bearing
 * properties — the relocation targets the credential provider keyed by the user's own id, copies the
 * bcrypt hash verbatim (no re-hash), only moves USABLE passwords, is additive (never touches
 * `users.password`) and idempotent (ON CONFLICT DO NOTHING) — so a later edit cannot silently break
 * the relocation or its reversibility.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V200__better_auth_credential_password_relocation_5000.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Better Auth credential-password relocation migration", () => {
  it("is present and ordered after the core-tables migration (V199)", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V199__better_auth_core_tables_4999.sql"),
    );
  });

  it("targets the apiome schema (search_path preserved)", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("relocates into account rows keyed by the literal 'credential' provider", () => {
    expect(lower).toContain("insert into apiome.account");
    expect(lower).toContain("from apiome.users");
    // The credential row uses providerId='credential' and accountId = the user's own id (§2.3).
    expect(lower).toContain("'credential'");
    expect(sql).toMatch(/u\.id::text/); // accountId = user id as text
  });

  it("copies the bcrypt hash verbatim (no re-hash) and does not carry OAuth token columns", () => {
    // The password column is populated straight from users.password — a byte-for-byte copy.
    expect(lower).toMatch(/"password"/);
    expect(lower).toMatch(/u\.password/);
    // No hashing/crypto happens in a SQL relocation.
    expect(lower).not.toContain("crypt(");
    expect(lower).not.toContain("gen_salt");
    // A credential row has no OAuth tokens.
    const backfill = lower.slice(lower.indexOf("insert into apiome.account"));
    expect(backfill).not.toContain("access_token");
    expect(backfill).not.toContain("refresh_token");
  });

  it("only relocates USABLE passwords (skips OAuth-only sentinel and soft-deleted users)", () => {
    // Empty-string password is the "no usable credential" sentinel (OAuth-provisioned users) — skip it.
    expect(lower).toMatch(/u\.password\s*<>\s*''/);
    expect(lower).toMatch(/u\.password\s+is\s+not\s+null/);
    // Do not relocate credentials for soft-deleted accounts.
    expect(lower).toMatch(/u\.deleted_at\s+is\s+null/);
  });

  it("is idempotent — ON CONFLICT keeps re-runs and post-cutover writes safe", () => {
    expect(lower).toMatch(/on conflict \("providerid", "accountid"\) do nothing/);
  });

  it("is additive / reversible — never mutates the legacy users.password source (§4 rollback)", () => {
    // The relocation must not drop, alter, or rewrite users / users.password (kept for rollback).
    expect(lower).not.toMatch(/drop table[^\n]*\busers\b/);
    expect(lower).not.toMatch(/alter table\s+(apiome\.)?users\b/);
    expect(lower).not.toMatch(/update\s+(apiome\.)?users\b/);
    expect(lower).not.toMatch(/delete\s+from\s+(apiome\.)?users\b/);
    // The documented rollback deletes only the relocated credential rows.
    expect(lower).toContain('delete from apiome.account where "providerid" = \'credential\'');
  });

  it("does not enable email/password sign-in for OAuth-only users (no empty-password rows)", () => {
    // Guard belt-and-suspenders: the WHERE clause both null-checks and empty-checks the password so a
    // NULL or '' can never become a credential row.
    const selectBlock = sql.slice(sql.indexOf("INSERT INTO apiome.account"));
    expect(selectBlock).toMatch(/WHERE[\s\S]*u\.password IS NOT NULL[\s\S]*u\.password <> ''/);
  });
});
