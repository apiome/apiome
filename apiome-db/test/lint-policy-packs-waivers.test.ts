/**
 * Structural assertions over the policy packs / waivers migration (#4850, CLX-1.3).
 *
 * V169 extends style guides into versioned policy packs, adds finding remediation/waiver
 * lifecycle with audit events, and append-only policy evaluations for CI gating.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V169__lint_policy_packs_waivers_4850.sql";

/** Closed finding lifecycle vocabulary from the CLX-1.3 contract. */
const DECISION_STATES = [
  "open",
  "acknowledged",
  "waived",
  "fixed",
  "false_positive",
] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("lint policy packs and waivers migration", () => {
  it("is present in scripts/ and ordered after V168", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V168__lint_axis_evaluations_4849.sql"),
    );
  });

  it("targets the apiome schema and creates tables idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(/create table if not exists style_guide_policy_versions/);
    expect(lower).toMatch(/create table if not exists lint_finding_decisions/);
    expect(lower).toMatch(/create table if not exists lint_finding_decision_events/);
    expect(lower).toMatch(/create table if not exists lint_policy_evaluations/);
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("style_guides draft gate columns", () => {
    it("adds axis_gates, required_coverage, and ci_outcomes", () => {
      expect(lower).toMatch(/alter table style_guides\s+add column if not exists axis_gates jsonb/);
      expect(lower).toMatch(
        /alter table style_guides\s+add column if not exists required_coverage jsonb/,
      );
      expect(lower).toMatch(
        /alter table style_guides\s+add column if not exists ci_outcomes jsonb/,
      );
    });
  });

  describe("style_guide_policy_versions", () => {
    it("defines every pack column from the CLX-1.3 field set", () => {
      for (const col of [
        "id",
        "guide_id",
        "tenant_id",
        "version_number",
        "content_fingerprint",
        "rules_snapshot",
        "axis_gates",
        "required_coverage",
        "ci_outcomes",
        "actor_user_id",
        "actor_label",
        "created_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("links to style_guides and tenants with cascade delete", () => {
      expect(lower).toMatch(
        /guide_id uuid not null references style_guides\(id\) on delete cascade/,
      );
      expect(lower).toMatch(
        /tenant_id uuid not null references tenants\(id\) on delete cascade/,
      );
    });

    it("enforces unique (guide_id, version_number) and positive version numbers", () => {
      expect(lower).toMatch(/style_guide_policy_versions_guide_version_uq\s+unique \(guide_id, version_number\)/);
      expect(lower).toMatch(/version_number >= 1/);
    });

    it("types rules_snapshot as array and gate fields as typed jsonb", () => {
      expect(lower).toMatch(/jsonb_typeof\(rules_snapshot\) = 'array'/);
      expect(lower).toMatch(/jsonb_typeof\(axis_gates\) = 'object'/);
      expect(lower).toMatch(/jsonb_typeof\(required_coverage\) = 'array'/);
      expect(lower).toMatch(/jsonb_typeof\(ci_outcomes\) = 'object'/);
    });

    it("defaults required_coverage to quality and CI outcomes to all enabled", () => {
      expect(lower).toMatch(/required_coverage jsonb not null default '\["quality"\]'::jsonb/);
      expect(lower).toMatch(/"failonunwaivederrors"\s*:\s*true/);
      expect(lower).toMatch(/"failonrequiredcoverage"\s*:\s*true/);
      expect(lower).toMatch(/"failonaxisgates"\s*:\s*true/);
    });

    it("attaches the write-once UPDATE-forbid trigger", () => {
      expect(lower).toMatch(
        /create trigger trigger_style_guide_policy_versions_immutable\s+before update on style_guide_policy_versions\s+for each row\s+execute function mcp_forbid_row_mutation\(\)/,
      );
    });
  });

  describe("lint_finding_decisions", () => {
    it("defines lifecycle and waiver columns", () => {
      for (const col of [
        "id",
        "tenant_id",
        "project_id",
        "source_fingerprint",
        "rule_id",
        "state",
        "owner_user_id",
        "rationale",
        "linked_ticket",
        "expires_at",
        "policy_version_id",
        "evidence_fingerprint_at_decision",
        "actor_user_id",
        "actor_label",
        "created_at",
        "updated_at",
      ]) {
        expect(sql).toMatch(new RegExp(`^\\s+${col}\\s`, "m"));
      }
    });

    it("constrains state to the closed lifecycle vocabulary", () => {
      expect(lower).toMatch(/lint_finding_decisions_state_check/);
      for (const state of DECISION_STATES) {
        expect(lower).toContain(`'${state}'`);
      }
    });

    it("requires rationale and expiry when waived", () => {
      expect(lower).toMatch(/lint_finding_decisions_waiver_fields_check/);
      expect(lower).toMatch(/state <> 'waived'/);
      expect(lower).toMatch(/expires_at is not null/);
    });

    it("uniquely indexes fingerprint per tenant (and per project when scoped)", () => {
      expect(lower).toMatch(
        /lint_finding_decisions_tenant_fp_uq\s+on lint_finding_decisions \(tenant_id, source_fingerprint\)\s+where project_id is null/,
      );
      expect(lower).toMatch(
        /lint_finding_decisions_project_fp_uq\s+on lint_finding_decisions \(project_id, source_fingerprint\)\s+where project_id is not null/,
      );
    });
  });

  describe("lint_finding_decision_events", () => {
    it("is append-only with write-once trigger", () => {
      expect(lower).toMatch(/create table if not exists lint_finding_decision_events/);
      expect(lower).toMatch(
        /create trigger trigger_lint_finding_decision_events_immutable\s+before update on lint_finding_decision_events\s+for each row\s+execute function mcp_forbid_row_mutation\(\)/,
      );
    });

    it("records before/after state, actor, and policy_version_id", () => {
      expect(lower).toMatch(/before_state text/);
      expect(lower).toMatch(/after_state text not null/);
      expect(lower).toMatch(/policy_version_id uuid references style_guide_policy_versions/);
      expect(lower).toMatch(/actor_user_id uuid references users/);
      expect(lower).toMatch(/actor_label text/);
    });
  });

  describe("lint_policy_evaluations", () => {
    it("links to catalog revisions and MCP snapshots with cascade delete", () => {
      expect(lower).toMatch(
        /version_record_id uuid references versions\(id\) on delete cascade/,
      );
      expect(lower).toMatch(
        /mcp_version_id uuid references mcp_endpoint_versions\(id\) on delete cascade/,
      );
    });

    it("constrains subject_type and enforces exactly one subject FK", () => {
      expect(lower).toMatch(
        /lint_policy_evaluations_subject_type_check\s+check \(subject_type in \('catalog_revision', 'mcp_endpoint_version'\)\)/,
      );
      expect(lower).toMatch(/lint_policy_evaluations_single_subject_check/);
      expect(lower).toMatch(
        /subject_type = 'catalog_revision'\s+and version_record_id is not null and mcp_version_id is null/,
      );
      expect(lower).toMatch(
        /subject_type = 'mcp_endpoint_version'\s+and mcp_version_id is not null and version_record_id is null/,
      );
    });

    it("pins a policy pack and stores gate_results plus finding_decisions", () => {
      expect(lower).toMatch(
        /policy_version_id uuid not null references style_guide_policy_versions\(id\) on delete restrict/,
      );
      expect(lower).toMatch(/policy_content_fingerprint text not null/);
      expect(lower).toMatch(/passed boolean not null/);
      expect(lower).toMatch(/gate_results jsonb not null default '{}'::jsonb/);
      expect(lower).toMatch(/finding_decisions jsonb not null default '\[\]'::jsonb/);
      expect(lower).toMatch(/jsonb_typeof\(gate_results\) = 'object'/);
      expect(lower).toMatch(/jsonb_typeof\(finding_decisions\) = 'array'/);
    });

    it("optionally links evidence runs and axis evaluations", () => {
      expect(lower).toMatch(
        /evidence_run_id uuid references lint_evidence_runs\(id\) on delete set null/,
      );
      expect(lower).toMatch(
        /axis_evaluation_id uuid references lint_axis_evaluations\(id\) on delete set null/,
      );
    });

    it("attaches the write-once UPDATE-forbid trigger", () => {
      expect(lower).toMatch(
        /create trigger trigger_lint_policy_evaluations_immutable\s+before update on lint_policy_evaluations\s+for each row\s+execute function mcp_forbid_row_mutation\(\)/,
      );
    });

    it("does not drop or redefine the shared V128 guard function", () => {
      expect(lower).not.toMatch(/drop function mcp_forbid_row_mutation/);
      expect(lower).not.toMatch(/create or replace function mcp_forbid_row_mutation/);
    });
  });

  describe("documentation", () => {
    it("comments the new tables and key columns", () => {
      expect(lower).toMatch(/comment on table style_guide_policy_versions is/);
      expect(lower).toMatch(/comment on table lint_finding_decisions is/);
      expect(lower).toMatch(/comment on table lint_finding_decision_events is/);
      expect(lower).toMatch(/comment on table lint_policy_evaluations is/);
      for (const col of [
        "content_fingerprint",
        "source_fingerprint",
        "policy_version_id",
        "gate_results",
        "finding_decisions",
      ]) {
        expect(lower).toMatch(new RegExp(`comment on column [a-z_]+\\.${col} is`));
      }
    });
  });
});
