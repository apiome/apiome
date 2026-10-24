/**
 * Structural assertions over the sign-up blocklist migration (SGN-1.5, #5654).
 *
 * V317 adds `apiome.signup_policy.blocked_email_domains`: the extra disposable domains a
 * super-admin refuses for email sign-up, on top of apiome-ui's bundled list. DB-free contract
 * tests pinning that shape; apiome-rest writes it in `Database.set_signup_policy` and apiome-ui
 * reads it in `lib/auth/signup-policy-resolver.ts`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V317__signup_blocked_email_domains_sgn_1_5.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
});

describe("sign-up blocked email domains migration (SGN-1.5 #5654)", () => {
  it("is present in scripts/ and ordered after V316", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V316__tenant_two_factor_policy_tfa_1_3.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain("alter table apiome.signup_policy");
  });

  it("adds an empty-by-default domain list", () => {
    expect(statements).toMatch(
      /add column if not exists blocked_email_domains text\[\] not null default '\{\}'::text\[\]/,
    );
  });

  it("bounds the list at 1000 entries, re-runnably", () => {
    expect(statements).toContain("check (cardinality(blocked_email_domains) <= 1000)");
    expect(statements).toContain("conname = 'signup_policy_blocked_email_domains_bounded'");
  });
});
