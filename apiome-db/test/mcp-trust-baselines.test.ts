/**
 * Structural assertions over the MCP trust-baseline migration (#4858, CLX-3.4).
 *
 * V174 adds one table:
 *   - `apiome.mcp_trust_baselines` — the operator-approved trust manifest an endpoint is measured
 *     against. Each row pins the approved snapshot, the composed trust-manifest fingerprint and full
 *     manifest envelope, the administrator RATIONALE, and the gating categories (configured risk
 *     deltas). Approving a new baseline supersedes the prior one; a partial unique index keeps exactly
 *     one live baseline per endpoint.
 *
 * DB-free contract tests pin the shape the acceptance criteria rest on: the non-blank rationale check
 * (AC2 — an approval must say why), the full manifest envelope stored for old→new evidence (AC1), the
 * one-live-baseline-per-endpoint partial unique index, and soft supersession (never a hard delete of
 * approval provenance).
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V174__mcp_trust_baselines_4858.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("mcp trust-baseline migration", () => {
  it("is present and ordered after V173", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V173__mcp_probe_runs_4857.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_trust_baselines/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });
});

describe("mcp trust-baseline approval evidence", () => {
  it("requires a non-blank administrator rationale (AC2)", () => {
    expect(lower).toContain("rationale");
    expect(lower).toContain("rationale_not_blank");
    expect(lower).toMatch(/check\s*\(\s*length\(trim\(rationale\)\)\s*>\s*0\s*\)/);
  });

  it("stores the approved snapshot, fingerprint, and full manifest envelope (AC1 old→new evidence)", () => {
    for (const col of ["version_id", "manifest_fingerprint", "manifest "]) {
      expect(lower).toContain(col);
    }
    expect(lower).toContain("manifest jsonb");
    expect(lower).toMatch(/check\s*\(\s*length\(trim\(manifest_fingerprint\)\)\s*>\s*0\s*\)/);
  });

  it("carries the configured gating categories (risk deltas that block)", () => {
    expect(lower).toContain("gating_categories");
    expect(sql).toContain("security_regression");
    expect(sql).toContain("coverage_loss");
  });
});

describe("mcp trust-baseline lifecycle", () => {
  it("keeps exactly one live baseline per endpoint via a partial unique index", () => {
    expect(lower).toMatch(
      /unique index[\s\S]*mcp_trust_baselines[\s\S]*\(endpoint_id\)[\s\S]*where superseded_at is null/,
    );
  });

  it("supersedes softly (superseded_at), never a hard delete of approval provenance", () => {
    expect(lower).toContain("superseded_at");
  });

  it("preserves approver provenance with a RESTRICT reference to users", () => {
    expect(lower).toMatch(/approved_by uuid references users \(id\) on delete restrict/);
  });

  it("cascades from its endpoint (and thus its tenant)", () => {
    expect(lower).toMatch(
      /endpoint_id uuid not null references mcp_endpoints[\s\S]*on delete cascade/,
    );
  });
});
