/**
 * Structural assertions over the multi-axis evaluation migration (#4849, CLX-1.2).
 *
 * V168 adds `apiome.lint_axis_evaluations` — the immutable, append-only score/coverage
 * substrate shared by catalog revisions and MCP discovery snapshots — plus a backfill from
 * both existing native report stores that maps legacy quality into the quality axis and leaves
 * peer axes as explicit not_assessed.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V168__lint_axis_evaluations_4849.sql";

/** Canonical axis keys from the CLX-1.2 contract, in evaluation order. */
const AXIS_KEYS = [
  "quality",
  "protocol",
  "security",
  "supply_chain",
  "supportability",
  "compatibility",
] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("lint axis evaluations migration", () => {
  it("is present in scripts/ and ordered after V167", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V167__lint_evidence_runs_4848.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists lint_axis_evaluations/);
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
        /lint_axis_evaluations_subject_type_check\s+check \(subject_type in \('catalog_revision', 'mcp_endpoint_version'\)\)/,
      );
    });

    it("enforces exactly one subject FK, agreeing with the discriminator", () => {
      expect(lower).toMatch(/lint_axis_evaluations_single_subject_check/);
      expect(lower).toMatch(
        /subject_type = 'catalog_revision'\s+and version_record_id is not null and mcp_version_id is null/,
      );
      expect(lower).toMatch(
        /subject_type = 'mcp_endpoint_version'\s+and mcp_version_id is not null and version_record_id is null/,
      );
    });
  });

  describe("evaluation contract columns", () => {
    it("defines every column from the CLX-1.2 field set", () => {
      for (const col of [
        "id",
        "subject_type",
        "version_record_id",
        "mcp_version_id",
        "algorithm_id",
        "algorithm_version",
        "axes",
        "composite_score",
        "composite_grade",
        "required_coverage_met",
        "source_report_fingerprint",
        "evaluated_at",
        "created_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("types axes as a JSON array", () => {
      expect(lower).toMatch(/axes jsonb not null default '\[\]'::jsonb/);
      expect(lower).toMatch(/jsonb_typeof\(axes\) = 'array'/);
    });

    it("constrains composite score to 0-100 when present", () => {
      expect(lower).toMatch(
        /composite_score is null or \(composite_score >= 0 and composite_score <= 100\)/,
      );
    });

    it("constrains composite grade to A-F letter bands", () => {
      expect(lower).toMatch(
        /composite_grade is null or composite_grade in \('a', 'b', 'c', 'd', 'f'\)/,
      );
    });
  });

  describe("immutability", () => {
    it("attaches the write-once UPDATE-forbid trigger (V128 guard)", () => {
      expect(lower).toMatch(
        /create trigger trigger_lint_axis_evaluations_immutable\s+before update on lint_axis_evaluations\s+for each row\s+execute function mcp_forbid_row_mutation\(\)/,
      );
    });

    it("does not drop or redefine the shared V128 guard function", () => {
      expect(lower).not.toMatch(/drop function mcp_forbid_row_mutation/);
      expect(lower).not.toMatch(/create or replace function mcp_forbid_row_mutation/);
    });
  });

  describe("indexes", () => {
    it("indexes latest-first per subject, partial per subject kind", () => {
      expect(lower).toMatch(
        /idx_lint_axis_evaluations_version\s+on lint_axis_evaluations \(version_record_id, evaluated_at desc\)\s+where version_record_id is not null/,
      );
      expect(lower).toMatch(
        /idx_lint_axis_evaluations_mcp_version\s+on lint_axis_evaluations \(mcp_version_id, evaluated_at desc\)\s+where mcp_version_id is not null/,
      );
    });

    it("indexes algorithm_id and non-null source report fingerprints", () => {
      expect(lower).toMatch(
        /idx_lint_axis_evaluations_algorithm\s+on lint_axis_evaluations \(algorithm_id\)/,
      );
      expect(lower).toMatch(
        /idx_lint_axis_evaluations_source_fingerprint\s+on lint_axis_evaluations \(source_report_fingerprint\)\s+where source_report_fingerprint is not null/,
      );
    });
  });

  describe("backfill", () => {
    it("stamps evaluations with clx-axis-v1", () => {
      expect(lower).toMatch(/'clx-axis-v1'/);
      expect(lower).toMatch(/algorithm_version/);
    });

    it("includes every canonical axis key", () => {
      for (const key of AXIS_KEYS) {
        expect(sql).toContain(`'${key}'`);
      }
    });

    it("marks peer axes as explicit not_assessed (never conflated with clean)", () => {
      expect(lower).toMatch(/'assessed', false/);
      expect(lower).toMatch(/'not_assessed_reason'/);
      expect(lower).toMatch(/coverage', jsonb_build_object\('state', 'none'\)/);
    });

    it("maps legacy quality into an assessed quality axis", () => {
      expect(lower).toMatch(/'key', 'quality'/);
      expect(lower).toMatch(/'assessed', true/);
      expect(lower).toMatch(/lint_axis_quality_assessed/);
    });

    it("backfills from both native report stores", () => {
      expect(lower).toMatch(/from versions v/);
      expect(lower).toMatch(/from mcp_version_scores s/);
    });

    it("preserves pre-existing report fingerprints as source_report_fingerprint", () => {
      expect(lower).toMatch(
        /coalesce\(v\.quality_report ->> 'report_fingerprint', v\.quality_report_fingerprint\)/,
      );
      expect(lower).toMatch(
        /coalesce\(s\.report ->> 'report_fingerprint', s\.report_fingerprint\)/,
      );
    });

    it("skips never-scored subjects", () => {
      expect(lower).toMatch(/v\.quality_score is not null/);
      expect(lower).toMatch(/s\.score is not null/);
    });

    it("is idempotent: each subject+algorithm+fingerprint backfills at most once", () => {
      expect(lower).toMatch(/not exists \(\s*select 1 from lint_axis_evaluations e/);
      expect(lower).toMatch(/e\.algorithm_id = 'clx-axis-v1'/);
    });

    it("publishes composite from quality when required coverage is met", () => {
      expect(lower).toMatch(/required_coverage_met/);
      expect(lower).toMatch(/\(v\.quality_score is not null\)/);
      expect(lower).toMatch(/\(s\.score is not null\)/);
    });
  });

  describe("documentation", () => {
    it("comments the table and key columns", () => {
      expect(lower).toMatch(/comment on table lint_axis_evaluations is/);
      for (const col of [
        "subject_type",
        "algorithm_id",
        "axes",
        "composite_score",
        "composite_grade",
        "required_coverage_met",
        "source_report_fingerprint",
      ]) {
        expect(lower).toMatch(
          new RegExp(`comment on column lint_axis_evaluations\\.${col} is`),
        );
      }
    });
  });
});
