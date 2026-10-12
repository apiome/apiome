/**
 * Structural assertions over the two-factor admin reset migration (#5656, TFA-1.2).
 *
 * V276 adds one nullable column, `users.two_factor_reset_at`, which the app reads to tell a user
 * their two-factor was reset by an administrator. The reset itself needs no schema — it deletes
 * rows the Better Auth tables already hold — so the contract worth pinning is that this migration
 * is additive, idempotent, and touches no existing data. Verified without a live database (this
 * package's suite is DB-free; the SQL is asserted structurally).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V276__two_factor_admin_reset_5656.sql";

/** The migration with `--` comment lines removed, so prose cannot satisfy a statement assertion. */
let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
});

describe("two-factor admin reset migration", () => {
  it("is present in scripts/ and ordered after V275", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V275__encrypt_linked_account_tokens_4960.sql"),
    );
  });

  it("adds the nullable reset timestamp idempotently", () => {
    expect(statements).toMatch(
      /ALTER TABLE apiome\.users\s+ADD COLUMN IF NOT EXISTS two_factor_reset_at TIMESTAMPTZ;/,
    );
    // No default and no NOT NULL: nobody has an outstanding reset until one happens.
    expect(statements).not.toMatch(/two_factor_reset_at[^;]*(NOT NULL|DEFAULT)/);
  });

  it("documents the column", () => {
    expect(statements).toContain("COMMENT ON COLUMN apiome.users.two_factor_reset_at IS");
  });

  it("changes no existing data and no other table", () => {
    expect(statements).not.toMatch(/\b(UPDATE|DELETE|INSERT|DROP|TRUNCATE)\b/i);
    expect(statements.match(/ALTER TABLE/g)).toHaveLength(1);
    expect(statements).not.toMatch(/CREATE (TABLE|INDEX)/i);
  });
});
