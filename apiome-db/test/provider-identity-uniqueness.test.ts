/**
 * Structural assertions over the provider-identity migration (#4187, OLO-1.2).
 *
 * V181 hardens `apiome.external_auth_providers`:
 *   - re-asserts the two uniqueness invariants (provider identity, one-per-provider-per-user),
 *   - adds the `email_verified` column and backfills it from stored profile JSON,
 *   - extends the supported provider vocabulary to include `azure`.
 *
 * These are DB-free contract tests pinning that shape so a later edit cannot silently regress the
 * "one provider identity = one user" and verified-email guarantees the OAuth epic depends on.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V181__provider_identity_uniqueness_4187.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("provider-identity uniqueness migration", () => {
  it("is present and ordered after V180", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V180__email_canonicalization_4186.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds the email_verified column idempotently, defaulting to false", () => {
    expect(lower).toMatch(
      /add column if not exists\s+email_verified\s+boolean not null default false/,
    );
  });

  it("ensures the email + last_login columns exist (self-contained on older schemas)", () => {
    expect(lower).toMatch(/add column if not exists\s+provider_email/);
    expect(lower).toMatch(/add column if not exists\s+last_login_at/);
  });

  it("backfills email_verified from the stored profile JSON verified signal", () => {
    expect(lower).toContain("update external_auth_providers");
    expect(lower).toContain("set email_verified = true");
    expect(lower).toContain("profile_data->>'email_verified'");
  });

  it("re-asserts both uniqueness invariants, guarded on pg_constraint", () => {
    expect(lower).toContain("from pg_constraint");
    expect(lower).toContain("unique (provider, provider_user_id)");
    expect(lower).toContain("unique (user_id, provider)");
  });

  it("pins the supported provider vocabulary including azure", () => {
    expect(lower).toContain("check (provider in (");
    expect(lower).toContain("'azure'");
    expect(lower).toContain("'github'");
    expect(lower).toContain("'gitlab'");
  });

  it("is idempotent — every DDL is guarded (IF NOT EXISTS / pg_constraint check)", () => {
    // No unguarded ADD CONSTRAINT: each ADD CONSTRAINT must sit inside a pg_constraint existence
    // check so re-runs / hand-built schemas are tolerated.
    const addConstraints = (lower.match(/add constraint/g) || []).length;
    const guards = (lower.match(/from pg_constraint/g) || []).length;
    expect(guards).toBeGreaterThanOrEqual(addConstraints);
  });
});
