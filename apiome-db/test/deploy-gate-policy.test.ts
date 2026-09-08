/**
 * Structural assertions over the deploy-gate policy migration (#4502, CTG-4.5).
 *
 * V254 adds `apiome.deploy_gate_policy`. The four signals a deploy gate aggregates — the GOV lint
 * grade, CTG-3.1's breaking classification, CTG-4.2's consumer verdicts and CTG-4.4's verification
 * freshness — are all already stored. The one thing the database did not hold is **where the bar
 * is**, and that is this table's entire job.
 *
 * DB-free contract tests pin the migration shape, concentrating on the four rules the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   1. **Two scopes, one shape.** `project_id IS NULL` is the tenant-wide policy; a row naming a
 *      project overrides it. Two *partial* unique indexes keep exactly one row per scope, so "the
 *      policy in force" is a lookup rather than a reduction over history — and so the two
 *      `ON CONFLICT … WHERE …` upserts apiome-rest issues have an index to resolve against.
 *   2. **The row is mutable, deliberately.** Every other policy table in the platform (ECA-3.1's
 *      verification policy, IXH-2.3's quality policy) is append-only, because a *stored* evaluation
 *      has to stay explicable against the policy version it was judged under. The gate stores no
 *      verdict, so there is no past judgment for a version history to explain; attribution lives in
 *      `access_audit`. The negative assertions below keep the row editable.
 *   3. **An absent row is not an absent policy.** Every threshold lives inside one JSONB body
 *      rather than as nullable columns, because "unset" (take the documented default) and "set to
 *      null" (disable that rung) are different answers, and only a document can say both.
 *   4. **A policy cannot outlive its scope.** Both foreign keys cascade.
 *
 * There is deliberately **no new RBAC resource**: reading a gate is `versions:view` and moving the
 * bar is `verification_targets:edit`, the same argument CTG-4.4 made for schedules.
 *
 * These must stay in lock-step with apiome-rest's `app.deploy_gate` contract
 * (`DeployGateThresholds`, `ctg.gate-policy.v1`) and its
 * `tests/test_deploy_gate_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V254__deploy_gate_policy_ctg_4_5.sql";
const TABLE = "deploy_gate_policy";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("deploy gate policy migration", () => {
  it("is present in scripts/ and ordered after the signals it sets the bar for", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V252__provider_verification_report_ctg_4_3.sql"),
    );
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V253__verification_schedule_ctg_4_4.sql"),
    );
  });

  it("targets the apiome schema and creates the table idempotently", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(lower).toMatch(new RegExp(`create table if not exists ${TABLE} \\(`));
  });

  it("uses uuid_generate_v4 conventions (no gen_random_uuid)", () => {
    expect(lower).toContain("uuid_generate_v4()");
    expect(lower).not.toContain("gen_random_uuid");
  });

  describe("rule 1 — two scopes, one row each", () => {
    it("carries the tenant and an optional project", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
      expect(lower).toContain("project_id uuid references projects(id) on delete cascade");
    });

    it("keeps one tenant-wide policy, via a partial unique index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TABLE}_tenant`);
      expect(lower).toMatch(
        new RegExp(`on ${TABLE} \\(tenant_id\\)\\s*\\n\\s*where project_id is null`),
      );
    });

    it("keeps one override per project, via the complementary partial index", () => {
      expect(lower).toContain(`create unique index if not exists idx_${TABLE}_project`);
      expect(lower).toMatch(
        new RegExp(
          `on ${TABLE} \\(tenant_id, project_id\\)\\s*\\n\\s*where project_id is not null`,
        ),
      );
    });
  });

  describe("rule 2 — the row is mutable, unlike every other policy table", () => {
    it("installs no immutability trigger", () => {
      expect(lower).not.toContain(`before update on ${TABLE}`);
      expect(lower).not.toContain("mcp_forbid_row_mutation");
    });

    it("tracks when and by whom it last changed", () => {
      expect(lower).toContain("updated_at timestamptz not null default current_timestamp");
      expect(lower).toContain("updated_by uuid references users(id) on delete set null");
    });

    it("does not take a version number, because there is no history to reduce", () => {
      expect(lower).not.toContain("version_number");
    });
  });

  describe("rule 3 — the thresholds are one document, not columns", () => {
    it("stores them as a JSONB object with a shape check", () => {
      expect(lower).toContain("thresholds jsonb not null default '{}'::jsonb");
      expect(lower).toContain(`constraint ${TABLE}_thresholds_object_check`);
      expect(lower).toContain("check (jsonb_typeof(thresholds) = 'object')");
    });

    it("fingerprints the body so a changed verdict can be attributed to a changed bar", () => {
      // 71 = "sha256:" + 64 hex characters, the same width every other fingerprint column uses.
      expect(lower).toContain("content_fingerprint varchar(71) not null");
    });

    it("names no individual threshold as a column", () => {
      for (const rung of [
        "warn_below_grade",
        "fail_below_grade",
        "fail_at_severity",
        "warn_after_seconds",
      ]) {
        expect(lower).not.toContain(rung);
      }
    });
  });

  describe("rule 4 — a policy cannot outlive its scope", () => {
    it("cascades from both the tenant and the project", () => {
      expect(sql.match(/ON DELETE CASCADE/g) ?? []).toHaveLength(2);
    });

    it("keeps provenance when a user is deleted rather than taking the gate with them", () => {
      expect(lower).toContain("created_by uuid references users(id) on delete set null");
      expect(lower).toContain("updated_by uuid references users(id) on delete set null");
    });
  });

  describe("the verification fallback's index", () => {
    it("indexes reports by the coordinates CTG-4.3 resolved, not by the reference string", () => {
      expect(lower).toContain(
        "create index if not exists idx_provider_verification_report_artifact",
      );
      expect(lower).toContain(
        "on provider_verification_report (tenant_id, artifact_kind, artifact_id, created_at desc)",
      );
    });

    it("is partial, because an unresolved artifact is unreachable by that question", () => {
      expect(lower).toContain("where artifact_id is not null");
    });
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles alone", () => {
      expect(lower).not.toContain("perform apiome.seed_builtin_roles");
      expect(lower).not.toContain("select apiome.seed_builtin_roles");
      expect(lower).not.toContain("create or replace function seed_builtin_roles");
    });

    it("touches no role or permission table", () => {
      expect(lower).not.toContain("insert into apiome.role_permissions");
      expect(lower).not.toContain("insert into role_permissions");
    });
  });

  it("documents its rollback, like every migration that adds a table", () => {
    expect(lower).toContain(`drop table if exists apiome.${TABLE};`);
    expect(lower).toContain("drop index if exists apiome.idx_provider_verification_report_artifact;");
  });
});
