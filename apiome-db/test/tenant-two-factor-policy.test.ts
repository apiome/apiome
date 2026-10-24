/**
 * Structural assertions over the tenant two-factor policy migration (TFA-1.3, #5657).
 *
 * V316 adds three `apiome.tenants` settings: `require_two_factor` (off by default),
 * `two_factor_grace_days` (default 7, 0–90) and `two_factor_required_since` (when the policy was
 * last turned on). DB-free contract tests pinning that shape; the statements apiome-rest runs
 * against it live in `apiome-rest/src/app/two_factor_policy.py`, and apiome-ui's enforcement read is
 * `lib/auth/two-factor-requirement-db.ts`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V316__tenant_two_factor_policy_tfa_1_3.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
});

describe("tenant two-factor policy migration (TFA-1.3 #5657)", () => {
  it("is present in scripts/ and ordered after V315", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V315__cli_login_requests_5501.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain("alter table tenants");
  });

  it("adds the switch off by default", () => {
    expect(statements).toMatch(
      /add column if not exists require_two_factor boolean not null default false/,
    );
  });

  it("adds a 7-day grace period bounded to 0–90 days", () => {
    expect(statements).toMatch(
      /add column if not exists two_factor_grace_days integer not null default 7/,
    );
    expect(statements).toContain("check (two_factor_grace_days between 0 and 90)");
    // Re-runnable: the constraint is only added when missing.
    expect(statements).toContain("conname = 'tenants_two_factor_grace_days_range'");
  });

  it("records when the policy was turned on, nullable while off", () => {
    expect(statements).toMatch(
      /add column if not exists two_factor_required_since timestamptz(?! not null)/,
    );
  });
});
