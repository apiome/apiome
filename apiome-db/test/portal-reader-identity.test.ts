/**
 * Structural assertions over the portal reader identity migration (#5889, PCX-1.1).
 *
 * V378 adds `portal_memberships`, `portal_magic_links` and `portal_reader_sessions` — the reader
 * principal Browse signs in with. DB-free contract tests pin the rules the ticket turns into schema:
 *
 *   1. **A reader is a user** — memberships reference `users`, unique per tenant and user, and the
 *      migration never touches `tenant_users` (a reader gets no workspace access).
 *   2. **Secrets are never stored** — only a bcrypt hash + lookup prefix (magic links) and a
 *      SHA-256 hash (sessions); no column named `token` or `secret`.
 *   3. **A token is burned once** — `consumed_at` and `expires_at` on every magic link.
 *   4. **Revocation is a stamp** — `revoked_at` columns, consistent with status by CHECK.
 *
 * Must stay in lock-step with apiome-rest's `app.portal_auth` vocabulary and its
 * `tests/test_portal_reader_identity_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V378__portal_reader_identity_pcx_1_1.sql";

/** The migration with `--` comments stripped, so prose cannot satisfy or trip an assertion. */
let statements = "";

/** The statements of one table's CREATE block (up to the next CREATE TABLE). */
function tableSection(table: string): string {
  const start = statements.indexOf(`create table if not exists ${table} (`);
  const next = statements.indexOf("create table if not exists", start + 1);
  return statements.slice(start, next === -1 ? undefined : next);
}

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n");
});

describe("portal reader identity migration", () => {
  it("is present in scripts/ and ordered after the previous migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V377__merge_requests_col_4_3.sql"),
    );
  });

  it("targets the apiome schema and creates every table idempotently", () => {
    expect(statements).toContain("set search_path to apiome, public");
    for (const table of ["portal_memberships", "portal_magic_links", "portal_reader_sessions"]) {
      expect(statements).toContain(`create table if not exists ${table} (`);
    }
    expect(statements).toContain("uuid_generate_v4()");
    expect(statements).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — a reader is a user", () => {
    it("references users and tenants, one membership per tenant and user", () => {
      const section = tableSection("portal_memberships");
      expect(section).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(section).toContain("user_id uuid not null references users(id) on delete cascade");
      expect(section).toContain("unique (tenant_id, user_id)");
    });

    it("closes the status and source vocabularies", () => {
      const section = tableSection("portal_memberships");
      expect(section).toContain("check (status in ('invited', 'active', 'revoked'))");
      expect(section).toContain("check (source in ('invite', 'magic_link', 'domain', 'sso'))");
    });

    it("never grants workspace access", () => {
      expect(statements).not.toContain("tenant_users");
      expect(statements).not.toContain("role_permissions");
    });
  });

  describe("rule 2 — secrets are never stored", () => {
    it("stores a lookup prefix and a hash for magic links", () => {
      const section = tableSection("portal_magic_links");
      expect(section).toContain("lookup_prefix varchar(32) not null");
      expect(section).toContain("token_hash varchar(255) not null");
    });

    it("stores a unique SHA-256 hash for sessions", () => {
      const section = tableSection("portal_reader_sessions");
      expect(section).toContain("token_hash char(64) not null");
      expect(section).toContain("portal_reader_sessions_token_hash_unique unique");
    });

    it("has no plaintext token, secret, IP or full user-agent column", () => {
      expect(statements).not.toMatch(/\n\s*(token|secret|ip_address|user_agent)\s/);
    });
  });

  it("rule 3 — magic links expire and are burned once", () => {
    const section = tableSection("portal_magic_links");
    expect(section).toContain("expires_at timestamp with time zone not null");
    expect(section).toContain("consumed_at timestamp with time zone");
  });

  it("rule 4 — revocation is a stamp consistent with status", () => {
    expect(tableSection("portal_memberships")).toContain(
      "check ((status = 'revoked') = (revoked_at is not null))",
    );
    expect(tableSection("portal_memberships")).toContain(
      "check (status <> 'active' or activated_at is not null)",
    );
    expect(tableSection("portal_reader_sessions")).toContain("revoked_at timestamp with time zone");
  });
});
