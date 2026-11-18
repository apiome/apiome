/**
 * Structural assertions over the SMS two-factor migration (#5071, OLO-9.51).
 *
 * V396 adds the Better Auth phoneNumber plugin's two user fields and apiome's per-user OTP
 * delivery channel. The contract worth pinning: additive and idempotent, existing users default to
 * email delivery, the channel is limited to the two known values, and a number belongs to one
 * account. Verified without a live database (this package's suite is DB-free).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V396__two_factor_sms_otp_5071.sql";

/** The migration with `--` comment lines removed, so prose cannot satisfy a statement assertion. */
let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
});

describe("two-factor SMS OTP migration", () => {
  it("is present in scripts/ and ordered after V395", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V395__auth_provider_vocabulary_full_catalog_5029.sql"),
    );
  });

  it("adds the Better Auth phoneNumber plugin fields in their native camelCase", () => {
    expect(statements).toMatch(/ADD COLUMN IF NOT EXISTS "phoneNumber" TEXT,/);
    expect(statements).toMatch(/ADD COLUMN IF NOT EXISTS "phoneNumberVerified" BOOLEAN DEFAULT FALSE,/);
  });

  it("defaults every existing user to email delivery", () => {
    expect(statements).toMatch(
      /ADD COLUMN IF NOT EXISTS two_factor_otp_channel TEXT NOT NULL DEFAULT 'email';/,
    );
  });

  it("limits the channel to email and sms, idempotently", () => {
    expect(statements).toContain("conname = 'users_two_factor_otp_channel_check'");
    expect(statements).toMatch(/CHECK \(two_factor_otp_channel IN \('email', 'sms'\)\)/);
  });

  it("gives a phone number to one account only", () => {
    expect(statements).toMatch(
      /CREATE UNIQUE INDEX IF NOT EXISTS users_phone_number_key ON apiome\.users \("phoneNumber"\);/,
    );
  });

  it("documents every new column", () => {
    expect(statements).toContain('COMMENT ON COLUMN apiome.users."phoneNumber" IS');
    expect(statements).toContain('COMMENT ON COLUMN apiome.users."phoneNumberVerified" IS');
    expect(statements).toContain("COMMENT ON COLUMN apiome.users.two_factor_otp_channel IS");
  });

  it("changes no existing data and no other table", () => {
    expect(statements).not.toMatch(/\b(UPDATE|DELETE|INSERT|DROP|TRUNCATE)\b/i);
    expect(statements).not.toMatch(/CREATE TABLE/i);
    expect(statements.match(/ALTER TABLE apiome\.(\w+)/g)?.every((m) => m.endsWith("users"))).toBe(
      true,
    );
  });
});
