/**
 * Structural assertions over the `apiome login` migration (#5501).
 *
 * V315 adds `apiome.cli_login_requests` (browser-approved CLI sign-in: device code stored as a
 * SHA-256 only, a short user code unique among live logins, a pending → approved | denied →
 * consumed lifecycle) and `api_keys.cli_login`, which marks the short-lived workspace keys the
 * flow mints. DB-free contract tests pinning that shape; the statements apiome-rest runs against it
 * live in `apiome-rest/src/app/cli_login_store.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V315__cli_login_requests_5501.sql";

let statements = "";

beforeAll(async () => {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  statements = sql
    .toLowerCase()
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join("\n");
});

describe("cli login migration (#5501)", () => {
  it("is present in scripts/ and ordered after V314", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V314__retire_signup_queue_sgn_1_3.sql"),
    );
  });

  it("targets the apiome schema and uses uuid_generate_v4", () => {
    expect(statements).toContain("set search_path to apiome, public");
    expect(statements).toContain("uuid_generate_v4()");
    expect(statements).not.toContain("gen_random_uuid");
  });

  it("marks CLI login keys, which must be expiring workspace keys", () => {
    expect(statements).toMatch(/add column if not exists cli_login boolean not null default false/);
    expect(statements).toMatch(
      /check \(not cli_login or \(kind = 'workspace' and expires_at is not null\)\)/,
    );
  });

  it("stores only the device code's hash, uniquely", () => {
    expect(statements).toMatch(/device_code_hash char\(64\) not null/);
    expect(statements).toContain("device_code_hash ~ '^[0-9a-f]{64}$'");
    expect(statements).toMatch(/unique index if not exists cli_login_requests_device_code_uq/);
    expect(statements).not.toMatch(/\bdevice_code\b(?!_)/);
  });

  it("keeps user codes unique among live logins only", () => {
    expect(statements).toMatch(
      /unique index if not exists cli_login_requests_live_user_code_uq\s+on apiome\.cli_login_requests \(user_code\)\s+where status in \('pending', 'approved'\)/,
    );
    expect(statements).toContain("user_code ~ '^[a-z0-9]{4}-[a-z0-9]{4}$'");
  });

  it("bounds the lifecycle and ties each state to its facts", () => {
    expect(statements).toContain("status in ('pending', 'approved', 'denied', 'consumed')");
    expect(statements).toContain("constraint cli_login_requests_decision_ck");
    expect(statements).toContain("constraint cli_login_requests_consumed_ck");
    expect(statements).toMatch(/expires_at timestamptz not null/);
  });

  it("cleans up with its owners", () => {
    expect(statements).toMatch(/user_id uuid references apiome\.users\(id\) on delete cascade/);
    expect(statements).toMatch(/tenant_id uuid references apiome\.tenants\(id\) on delete cascade/);
    expect(statements).toMatch(/api_key_id uuid references apiome\.api_keys\(id\) on delete set null/);
  });
});
