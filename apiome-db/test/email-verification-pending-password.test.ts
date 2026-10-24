/**
 * Structural assertions over the sign-up link binding migration (RC6 security review, B6).
 *
 * V318 adds `pending_password_hash` and `pending_name` to `apiome.email_verification_token`: each
 * link carries the password submitted with the sign-up that sent it, and apiome-ui's
 * `redeemVerificationToken` makes that password the account's only credential once the redeemer
 * enters it — closing account pre-hijacking through email sign-up. DB-free contract tests pinning
 * that shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V318__email_verification_pending_password.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
});

describe("email verification pending password migration (RC6 B6)", () => {
  it("is present in scripts/ and ordered after V317", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V317__signup_blocked_email_domains_sgn_1_5.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain("alter table apiome.email_verification_token");
  });

  it("adds two nullable columns, so links issued before it keep working", () => {
    expect(statements).toContain("add column if not exists pending_password_hash text,");
    expect(statements).toContain("add column if not exists pending_name text;");
    expect(statements).not.toMatch(/pending_password_hash text not null/);
  });

  it("accepts only a bcrypt hash, re-runnably", () => {
    expect(statements).toContain("conname = 'email_verification_token_pending_hash_ck'");
    expect(statements).toContain("pending_password_hash is null or pending_password_hash ~");
  });
});
