/**
 * Structural assertions over the revision-scoped lint evidence migration (#4848, CLX-1.1).
 *
 * V167 adds `apiome.lint_evidence_runs` — the immutable, append-only evidence substrate shared
 * by catalog revisions (`versions`) and MCP discovery snapshots (`mcp_endpoint_versions`) —
 * plus a backfill from both existing native report stores that preserves the pre-existing
 * report fingerprints byte-for-byte.
 *
 * DB-free contract tests pin the migration shape: the polymorphic single-subject constraint,
 * the closed outcome vocabulary, the write-once trigger, the finding-envelope projection the
 * backfill applies (which must stay in lock-step with apiome-rest's
 * `app.lint_evidence.normalize_native_finding`), and fingerprint preservation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V167__lint_evidence_runs_4848.sql";

/** The closed outcome vocabulary from the CLX-1.1 contract, in migration order. */
const OUTCOMES = [
  "passed",
  "findings",
  "not_run",
  "unavailable",
  "failed",
  "blocked_by_policy",
] as const;

/** Every envelope key the backfill's finding projection must emit (source-neutral contract). */
const ENVELOPE_KEYS = [
  "rule_id",
  "message",
  "severity",
  "confidence",
  "category",
  "location",
  "remediation",
  "source_fingerprint",
] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("lint evidence runs migration", () => {
  it("is present in scripts/ and ordered after V166", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V166__tenant_mcp_policy_changes_4786.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists lint_evidence_runs/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("subject linkage", () => {
    it("links to catalog revisions and MCP snapshots with cascade delete", () => {
      expect(lower).toMatch(
        /version_record_id uuid references versions\(id\) on delete cascade/,
      );
      expect(lower).toMatch(
        /mcp_version_id uuid references mcp_endpoint_versions\(id\) on delete cascade/,
      );
    });

    it("constrains subject_type to the two known subject kinds", () => {
      expect(lower).toMatch(
        /lint_evidence_runs_subject_type_check\s+check \(subject_type in \('catalog_revision', 'mcp_endpoint_version'\)\)/,
      );
    });

    it("enforces exactly one subject FK, agreeing with the discriminator", () => {
      expect(lower).toMatch(/lint_evidence_runs_single_subject_check/);
      expect(lower).toMatch(
        /subject_type = 'catalog_revision'\s+and version_record_id is not null and mcp_version_id is null/,
      );
      expect(lower).toMatch(
        /subject_type = 'mcp_endpoint_version'\s+and mcp_version_id is not null and version_record_id is null/,
      );
    });
  });

  describe("evidence contract columns", () => {
    it("defines every column from the ticket's field set", () => {
      for (const col of [
        "id",
        "subject_type",
        "version_record_id",
        "mcp_version_id",
        "scanner_id",
        "scanner_version",
        "adapter_version",
        "profile",
        "started_at",
        "finished_at",
        "outcome",
        "input_fingerprint",
        "source_fingerprint",
        "config_fingerprint",
        "raw_artifact_ref",
        "report_fingerprint",
        "findings",
        "coverage",
        "envelope_version",
        "created_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("constrains outcome to the closed CLX-1.1 vocabulary", () => {
      expect(lower).toMatch(/lint_evidence_runs_outcome_check/);
      const quoted = OUTCOMES.map((o) => `'${o}'`).join(",\\s*");
      expect(lower).toMatch(
        new RegExp(`check \\(outcome in \\(${quoted}\\)\\)`),
      );
    });

    it("types findings as a JSON array and coverage as a JSON object", () => {
      expect(lower).toMatch(/findings jsonb not null default '\[\]'::jsonb/);
      expect(lower).toMatch(/jsonb_typeof\(findings\) = 'array'/);
      expect(lower).toMatch(/jsonb_typeof\(coverage\) = 'object'/);
    });

    it("rejects a run that finishes before it starts", () => {
      expect(lower).toMatch(
        /started_at is null or finished_at is null or finished_at >= started_at/,
      );
    });

    it("versions the finding-envelope contract, starting at 1", () => {
      expect(lower).toMatch(/envelope_version smallint not null default 1/);
      expect(lower).toMatch(/check \(envelope_version >= 1\)/);
    });
  });

  describe("immutability", () => {
    it("attaches the write-once UPDATE-forbid trigger (V128 guard)", () => {
      expect(lower).toMatch(
        /create trigger trigger_lint_evidence_runs_immutable\s+before update on lint_evidence_runs\s+for each row\s+execute function mcp_forbid_row_mutation\(\)/,
      );
    });

    it("does not drop or redefine the shared V128 guard function", () => {
      expect(lower).not.toMatch(/drop function/);
      expect(lower).not.toMatch(/create or replace function mcp_forbid_row_mutation/);
    });
  });

  describe("indexes", () => {
    it("indexes latest-first per subject, partial per subject kind", () => {
      expect(lower).toMatch(
        /idx_lint_evidence_runs_version\s+on lint_evidence_runs \(version_record_id, created_at desc\)\s+where version_record_id is not null/,
      );
      expect(lower).toMatch(
        /idx_lint_evidence_runs_mcp_version\s+on lint_evidence_runs \(mcp_version_id, created_at desc\)\s+where mcp_version_id is not null/,
      );
    });

    it("indexes scanner_id and non-null report fingerprints", () => {
      expect(lower).toMatch(/idx_lint_evidence_runs_scanner\s+on lint_evidence_runs \(scanner_id\)/);
      expect(lower).toMatch(
        /idx_lint_evidence_runs_report_fingerprint\s+on lint_evidence_runs \(report_fingerprint\)\s+where report_fingerprint is not null/,
      );
    });
  });

  describe("backfill", () => {
    it("backfills from both native report stores", () => {
      expect(lower).toMatch(/from versions v/);
      expect(lower).toMatch(/from mcp_version_scores s/);
      expect(lower).toMatch(/join mcp_endpoint_versions mv on mv\.id = s\.version_id/);
    });

    it("preserves pre-existing report fingerprints verbatim", () => {
      expect(lower).toMatch(
        /coalesce\(v\.quality_report ->> 'report_fingerprint', v\.quality_report_fingerprint\)/,
      );
      expect(lower).toMatch(
        /coalesce\(s\.report ->> 'report_fingerprint', s\.report_fingerprint\)/,
      );
    });

    it("skips never-scored subjects so their coverage reads not_run, not clean", () => {
      // Only rows with a non-empty report or a captured fingerprint get evidence.
      expect(lower).toMatch(/v\.quality_report <> '{}'::jsonb/);
      expect(lower).toMatch(/or v\.quality_report_fingerprint is not null/);
      expect(lower).toMatch(/s\.report <> '{}'::jsonb/);
      expect(lower).toMatch(/or s\.report_fingerprint is not null/);
    });

    it("is idempotent: each subject+scanner backfills at most once", () => {
      expect(lower).toMatch(
        /not exists \(\s*select 1 from lint_evidence_runs r\s+where r\.version_record_id = v\.id and r\.scanner_id = 'apiome\.native-lint'/,
      );
      expect(lower).toMatch(
        /not exists \(\s*select 1 from lint_evidence_runs r\s+where r\.mcp_version_id = s\.version_id and r\.scanner_id = 'apiome\.mcp-lint'/,
      );
    });

    it("projects legacy findings into the full source-neutral envelope", () => {
      for (const key of ENVELOPE_KEYS) {
        expect(sql).toMatch(new RegExp(`'${key}'`));
      }
      // Legacy dict fields feed the envelope: rule -> rule_id, path -> location.path,
      // id -> source_fingerprint; native lint is deterministic, so confidence is high.
      expect(lower).toMatch(/'rule_id', f ->> 'rule'/);
      expect(lower).toMatch(/'location', jsonb_build_object\('path', f ->> 'path'\)/);
      expect(lower).toMatch(/'source_fingerprint', f ->> 'id'/);
      expect(lower).toMatch(/'confidence', 'high'/);
    });

    it("stamps backfilled runs with adapter, profile, scanner id, and full coverage", () => {
      expect(lower).toMatch(/'backfill:v167'/);
      expect(lower).toMatch(/'import-capture'/);
      expect(lower).toMatch(/'discovery-capture'/);
      expect(lower).toMatch(/'apiome\.native-lint'/);
      expect(lower).toMatch(/'apiome\.mcp-lint'/);
      expect(lower).toMatch(/'{"state": "full"}'::jsonb/);
    });

    it("carries the MCP snapshot's surface fingerprint as the input identity", () => {
      expect(lower).toMatch(/mv\.surface_fingerprint/);
    });
  });

  describe("documentation", () => {
    it("comments the table and every column", () => {
      expect(lower).toMatch(/comment on table lint_evidence_runs is/);
      for (const col of [
        "subject_type",
        "scanner_id",
        "adapter_version",
        "outcome",
        "config_fingerprint",
        "raw_artifact_ref",
        "report_fingerprint",
        "findings",
        "coverage",
        "envelope_version",
      ]) {
        expect(lower).toMatch(
          new RegExp(`comment on column lint_evidence_runs\\.${col} is`),
        );
      }
    });
  });
});
