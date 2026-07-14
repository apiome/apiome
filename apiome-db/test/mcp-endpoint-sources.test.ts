/**
 * Structural assertions over the MCP source association migration (#4856, CLX-3.2).
 *
 * V172 adds two tables:
 *   - `apiome.mcp_endpoint_sources` — the explicit link from an MCP endpoint to the git repo /
 *     package / image / registry identity it is built from, recording provenance and pin strength
 *     as two independent axes.
 *   - `apiome.mcp_source_sboms` — the immutable, coordinates-only dependency inventory of one
 *     pinned artifact.
 *
 * DB-free contract tests pin the migration shape: the two-axis check constraints, the
 * pin-strength invariant (a source cannot claim to be pinned without a digest), the write-once
 * trigger on SBOMs, and the "no column for source content" guarantee that backs the
 * no-exfiltration acceptance criterion.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V172__mcp_endpoint_sources_4856.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("mcp source associations migration", () => {
  it("is present and ordered after V171", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V171__mcp_protocol_transcripts_4855.sql"),
    );
  });

  it("targets the apiome schema and creates both tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists mcp_endpoint_sources/);
    expect(lower).toMatch(/create table if not exists mcp_source_sboms/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  it("constrains source_kind, provenance, and verification_state to closed vocabularies", () => {
    for (const kind of ["'git'", "'package'", "'image'", "'registry'"]) {
      expect(sql).toContain(kind);
    }
    for (const prov of ["'operator_declared'", "'registry_published'", "'discovery_advertised'", "'attested'"]) {
      expect(sql).toContain(prov);
    }
    for (const state of ["'unverified'", "'digest_pinned'", "'attested'"]) {
      expect(sql).toContain(state);
    }
  });

  it("enforces the pin-strength invariant: a pinned source must carry a digest", () => {
    // The CHECK that makes 'digest_pinned' on a row with no digest unstorable — the schema-level
    // guarantee behind the whole confidence model.
    expect(lower).toContain("pinned_needs_digest");
    expect(lower).toMatch(/verification_state\s*=\s*'unverified'\s+or\s*\(\s*digest\s+is\s+not\s+null/);
  });

  it("keeps provenance and verification_state as two independent columns", () => {
    // Collapsing them into one 'trust level' would lose the distinction a reviewer needs.
    expect(lower).toContain("provenance ");
    expect(lower).toContain("verification_state ");
  });

  it("scopes a live source uniquely per (endpoint, kind, locator) excluding retired rows", () => {
    expect(lower).toMatch(/unique index[\s\S]*mcp_endpoint_sources[\s\S]*where retired_at is null/);
  });

  it("retires sources softly (retired_at), never a hard delete of provenance", () => {
    expect(lower).toContain("retired_at");
  });
});

describe("mcp source SBOMs migration", () => {
  it("stores component coordinates only — no column can hold source content", () => {
    // The no-exfiltration guarantee is enforced by shape: the components column is JSONB
    // coordinates, and there is deliberately no source/content/blob column.
    expect(lower).toContain("components ");
    expect(lower).not.toMatch(/\bsource_content\b/);
    expect(lower).not.toMatch(/\bfile_content\b/);
    expect(lower).not.toMatch(/\braw_source\b/);
  });

  it("constrains sbom_format and origin to closed vocabularies", () => {
    for (const fmt of ["'cyclonedx'", "'spdx'", "'apiome-manifest'"]) {
      expect(sql).toContain(fmt);
    }
    for (const origin of ["'operator_supplied'", "'manifest_derived'"]) {
      expect(sql).toContain(origin);
    }
  });

  it("is write-once via the shared V128 mutation guard", () => {
    expect(lower).toContain("mcp_forbid_row_mutation");
    expect(lower).toMatch(/before update on mcp_source_sboms/);
  });

  it("keys an inventory by (source, artifact digest, origin)", () => {
    expect(lower).toMatch(/unique index[\s\S]*mcp_source_sboms[\s\S]*subject_digest/);
  });

  it("cascades from its source (and thus its endpoint and tenant)", () => {
    expect(lower).toMatch(/references mcp_endpoint_sources[\s\S]*on delete cascade/);
  });
});
