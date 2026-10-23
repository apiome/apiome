/**
 * Structural assertions over the sign-up queue retirement migration (#5652, SGN-1.3).
 *
 * V314 makes the legacy `apiome.signup` queue read-only (a trigger refuses every write, TRUNCATE
 * included) and adds `apiome.legacy_signup_invitation`, the claim ledger apiome-ui uses to email
 * each queued address once. The queue is kept (not dropped) for one release.
 *
 * These are DB-free contract tests pinning that shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V314__retire_signup_queue_sgn_1_3.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

/** The migration with its `--` comment lines removed, so assertions see only statements. */
const statements = () =>
  lower
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");

describe("retire sign-up queue migration (SGN-1.3)", () => {
  it("is present in scripts/ and ordered after V313", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V313__email_verification_token_sgn_1_1.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("keeps the queue table for one release (no drop)", () => {
    expect(statements()).not.toMatch(/drop\s+table[^;]*\bsignup\b(?!_)/);
  });

  it("refuses every row write and TRUNCATE on apiome.signup", () => {
    const sql = statements();
    expect(sql).toMatch(
      /before insert or update or delete on apiome\.signup\s+for each row execute function apiome\.signup_read_only\(\)/,
    );
    expect(sql).toMatch(
      /before truncate on apiome\.signup\s+for each statement execute function apiome\.signup_read_only\(\)/,
    );
    expect(sql).toContain("raise exception");
    expect(sql).toContain("read_only_sql_transaction");
  });

  it("adds the invitation ledger keyed by address with a bounded outcome", () => {
    const sql = statements();
    expect(sql).toMatch(/create table if not exists apiome\.legacy_signup_invitation/);
    expect(sql).toMatch(/email_address varchar\(255\) primary key/);
    expect(sql).toMatch(/check \(outcome in \('sent', 'account_exists'\)\)/);
  });

  it("is re-runnable (idempotent DDL)", () => {
    const sql = statements();
    expect(sql).toContain("create or replace function apiome.signup_read_only()");
    expect(sql).toContain("drop trigger if exists signup_read_only_trg on apiome.signup");
    expect(sql).toContain("drop trigger if exists signup_read_only_truncate_trg on apiome.signup");
  });
});
