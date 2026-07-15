/**
 * Structural assertions over the MCP dynamic-probe migration (#4857, CLX-3.3).
 *
 * V173 adds two tables:
 *   - `apiome.mcp_probe_targets` — the ALLOWLIST an active probe may fire at. Enrolling requires the
 *     operator's ownership assertion and names the dedicated (non-production) test credential.
 *   - `apiome.mcp_probe_runs` — the AUDIT TRAIL and per-tenant concurrency/rate ledger. One row per
 *     active run recording target, scope, test identity, limits, consent, isolation, and outcome.
 *
 * DB-free contract tests pin the shape the acceptance criteria rest on: the ownership-required check
 * on the allowlist, the closed profile/transport/status vocabularies, the "a refused run must say
 * why" and "a running run has no outcome" honesty checks, and the partial index the concurrency
 * ledger is read through. Passive probing is intentionally NOT modelled here (it sends nothing), so
 * the profile check excludes 'passive'.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V173__mcp_probe_runs_4857.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("mcp probe migration", () => {
  it("is present and ordered after V172", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V172__mcp_endpoint_sources_4856.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_probe_targets/);
    expect(lower).toMatch(/create table if not exists mcp_probe_runs/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });
});

describe("mcp probe allowlist", () => {
  it("requires an ownership declaration to store an entry", () => {
    // The schema refuses an allowlist row that did not carry the authorization assertion — probing a
    // system nobody vouched for is exactly what the allowlist exists to prevent.
    expect(lower).toContain("ownership_required");
    expect(lower).toMatch(/check\s*\(\s*ownership_declared\s*=\s*true\s*\)/);
  });

  it("names a dedicated test credential, referencing mcp_endpoint_credentials", () => {
    expect(lower).toContain("test_credential_id");
    expect(lower).toMatch(/references mcp_endpoint_credentials/);
  });

  it("constrains transport to http/stdio and scopes a live entry per (endpoint, transport)", () => {
    expect(sql).toContain("'http'");
    expect(sql).toContain("'stdio'");
    expect(lower).toMatch(/unique index[\s\S]*mcp_probe_targets[\s\S]*where retired_at is null/);
  });

  it("retires targets softly (retired_at), never a hard delete of provenance", () => {
    expect(lower).toContain("retired_at");
  });
});

describe("mcp probe runs audit trail", () => {
  it("records target, scope, test identity, limits, consent, and isolation (AC2)", () => {
    for (const col of [
      "target_locator",
      "profile",
      "consent ",
      "limits ",
      "isolation",
    ]) {
      expect(lower).toContain(col);
    }
  });

  it("excludes passive from the profile vocabulary (passive sends nothing, so is never recorded)", () => {
    expect(sql).toContain("'safe-active'");
    expect(sql).toContain("'payload-fuzzing'");
    expect(lower).toMatch(/profile in \('safe-active', 'payload-fuzzing'\)/);
  });

  it("constrains status to a closed lifecycle vocabulary", () => {
    for (const status of ["'running'", "'completed'", "'refused'", "'failed'"]) {
      expect(sql).toContain(status);
    }
  });

  it("keeps the ledger honest: a refused run states why, a running run has no outcome", () => {
    expect(lower).toContain("refusal_has_reason");
    expect(lower).toMatch(/status\s*<>\s*'refused'\s+or\s+refusal_reason\s+is\s+not\s+null/);
    expect(lower).toContain("running_has_no_outcome");
    expect(lower).toMatch(/status\s*<>\s*'running'\s+or\s*\(\s*report\s+is\s+null/);
  });

  it("is the concurrency ledger: a partial index over in-flight runs per tenant", () => {
    expect(lower).toMatch(/create index[\s\S]*mcp_probe_runs[\s\S]*where status = 'running'/);
  });

  it("cascades from its endpoint (and thus its tenant)", () => {
    expect(lower).toMatch(/endpoint_id uuid not null references mcp_endpoints[\s\S]*on delete cascade/);
  });
});
