/**
 * Structural assertions over the email canonicalization migration (#4186, OLO-1.1).
 *
 * V180 makes `apiome.users.email` case-insensitively unique:
 *   - drops the byte-exact `users_email_key` constraint from V001,
 *   - surfaces existing case-collision duplicates into an audit table (never auto-merging them),
 *   - quarantines the non-canonical rows so the index can build,
 *   - normalizes every address to `lower(trim(...))`,
 *   - and enforces uniqueness with a functional partial unique index on `lower(email)`.
 *
 * These are DB-free contract tests pinning that shape so a later edit cannot silently regress the
 * "duplicate-cased signups are impossible" guarantee.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V180__email_canonicalization_4186.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("email canonicalization migration", () => {
  it("is present and ordered after V179", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V179__push_webhook_min_severity_4477.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates the conflict audit table idempotently with the resolution columns", () => {
    expect(lower).toMatch(/create table if not exists apiome\.email_canonicalization_conflicts/);
    for (const col of [
      "user_id",
      "original_email",
      "normalized_email",
      "is_canonical",
      "action_taken",
    ]) {
      expect(lower).toContain(col);
    }
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("drops the byte-exact V001 unique constraint so normalization cannot collide", () => {
    expect(lower).toMatch(/drop constraint if exists users_email_key/);
  });

  it("surfaces duplicates into the audit table rather than merging them", () => {
    // The audit population must run before the quarantine so every colliding row is recorded.
    const insertIdx = lower.indexOf("insert into apiome.email_canonicalization_conflicts");
    expect(insertIdx).toBeGreaterThan(-1);
    expect(lower).toContain("having count(*) > 1");
    expect(lower).toContain("'kept_active'");
    expect(lower).toContain("'quarantined'");
    // No blanket delete/merge of user rows — duplicates are soft-deleted, not removed.
    expect(lower).not.toMatch(/delete\s+from\s+apiome\.users/);
  });

  it("quarantines non-canonical duplicates by soft-deleting (never hard-deleting) them", () => {
    expect(lower).toMatch(/update\s+apiome\.users/);
    expect(lower).toContain("deleted_at = current_timestamp");
    expect(lower).toContain("enabled = false");
    expect(lower).toContain("action_taken = 'quarantined'");
  });

  it("keeps the earliest-created row canonical", () => {
    expect(lower).toContain("row_number() over");
    expect(lower).toMatch(/order by\s+u\.created_at asc/);
  });

  it("normalizes stored addresses to lower(trim(email))", () => {
    expect(lower).toContain("set email = lower(trim(email))");
  });

  it("enforces case-insensitive uniqueness with a functional partial unique index", () => {
    expect(lower).toMatch(/create unique index if not exists uq_users_email_lower/);
    expect(lower).toContain("(lower(email))");
    expect(lower).toContain("where deleted_at is null");
  });

  it("retires the now-redundant case-sensitive lookup index", () => {
    expect(lower).toMatch(/drop index if exists apiome\.idx_users_email/);
  });
});
