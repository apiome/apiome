/**
 * Structural assertions over the Better Auth core-tables migration (#4999, OLO-10.4).
 *
 * V199 creates the three Better Auth core tables that did not exist before — `session`, `account`,
 * `verification` — with Better Auth's native (quoted, camelCase) column names, plus the OLO-1.2
 * identity-uniqueness constraints on `account` and the backfill of `account` from the existing
 * `external_auth_providers` OAuth identities. See docs/BETTER_AUTH_MIGRATION.md §2.
 *
 * These are DB-free contract tests: they read the migration text and pin the shape Better Auth reads
 * (column names/types, the uniqueness invariant, additivity/idempotency) so a later edit cannot
 * silently drift the schema away from what the Better Auth instance (apiome-ui/lib/auth/auth.ts,
 * no field mapping) expects.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V199__better_auth_core_tables_4999.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Better Auth core-tables migration", () => {
  it("is present and ordered after V198", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V198__auth_provider_vocabulary_4984.sql"),
    );
  });

  it("targets the apiome schema (search_path preserved)", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates all three core tables, guarded (IF NOT EXISTS)", () => {
    expect(lower).toMatch(/create table if not exists apiome\.session\b/);
    expect(lower).toMatch(/create table if not exists apiome\.account\b/);
    expect(lower).toMatch(/create table if not exists apiome\.verification\b/);
  });

  it("uses Better Auth's native quoted camelCase columns (not snake_case)", () => {
    // Session (issue: token/expiresAt/ipAddress/userAgent) + userId FK.
    for (const col of ['"userId"', '"token"', '"expiresAt"', '"ipAddress"', '"userAgent"']) {
      expect(sql).toContain(col);
    }
    // Account (issue: providerId/accountId/accessTokenExpiresAt/refreshTokenExpiresAt/password).
    for (const col of [
      '"providerId"',
      '"accountId"',
      '"accessTokenExpiresAt"',
      '"refreshTokenExpiresAt"',
      '"password"',
    ]) {
      expect(sql).toContain(col);
    }
    // Verification (issue: id/value/expiresAt) + identifier.
    for (const col of ['"identifier"', '"value"']) {
      expect(sql).toContain(col);
    }
  });

  it("makes new-table ids TEXT (Better Auth-generated) and userId a UUID FK onto users", () => {
    expect(lower).toMatch(/"id"\s+text primary key/);
    // Both session and account reference users(id) with ON DELETE CASCADE via a UUID userId.
    const fkMatches = lower.match(
      /"userid"\s+uuid not null references apiome\.users\(id\) on delete cascade/g,
    );
    expect(fkMatches?.length).toBe(2);
  });

  it("stores dates as timestamptz", () => {
    expect(lower).toMatch(/"expiresat"\s+timestamptz not null/);
  });

  it("lands the OLO-1.2 identity-uniqueness invariant WITH the account table", () => {
    expect(lower).toContain('unique ("providerid", "accountid")');
    expect(lower).toContain('unique ("userid", "providerid")');
  });

  it("carries the resolution-engine columns onto account (not dropped)", () => {
    expect(lower).toMatch(/provider_email\s+varchar/);
    expect(lower).toMatch(/email_verified\s+boolean not null default false/);
    expect(lower).toMatch(/profile_data\s+jsonb/);
  });

  it("backfills account from external_auth_providers, idempotently", () => {
    expect(lower).toContain("insert into apiome.account");
    expect(lower).toContain("from apiome.external_auth_providers");
    // provider → providerId and provider_user_id → accountId mapping is present in the select.
    expect(lower).toContain("eap.provider");
    expect(lower).toContain("eap.provider_user_id");
    // ON CONFLICT on the identity key keeps re-runs safe.
    expect(lower).toMatch(/on conflict \("providerid", "accountid"\) do nothing/);
  });

  it("is additive — does not drop or alter the legacy source tables (rollback safety §4)", () => {
    // No destructive DDL against users / external_auth_providers (kept as source of truth until 10.14).
    expect(lower).not.toMatch(/drop table[^\n]*\b(users|external_auth_providers)\b/);
    expect(lower).not.toMatch(/alter table\s+(apiome\.)?users\b/);
    expect(lower).not.toMatch(/alter table\s+(apiome\.)?external_auth_providers\b/);
    // Password DATA relocation is 10.5, not here: the backfill neither reads users nor moves a
    // password. Scope the check to the INSERT..SELECT block (the header comment may name the column).
    const backfill = lower.slice(lower.indexOf("insert into apiome.account"));
    expect(backfill).not.toContain("password");
    expect(backfill).not.toContain("from apiome.users");
  });

  it("indexes the hot paths (session owner/expiry, verification identifier)", () => {
    expect(lower).toMatch(/create index if not exists .*on apiome\.session \("userid"\)/);
    expect(lower).toMatch(/create index if not exists .*on apiome\.session \("expiresat"\)/);
    expect(lower).toMatch(
      /create index if not exists .*on apiome\.verification \("identifier"\)/,
    );
  });
});
