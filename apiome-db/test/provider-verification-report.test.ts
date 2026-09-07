/**
 * Structural assertions over the provider verification report migration (#4489, CTG-4.3).
 *
 * V252 adds `apiome.provider_verification_report`: the conformance report written beside each
 * verification run. V212 already stores what a run *did* — one row per executed case — but it
 * cannot answer the question a deploy gate asks: *how much of this contract did that run check,
 * and where did the deployment disagree?* Coverage has no denominator in the evidence tables, and
 * the per-operation drift picture would otherwise be recomputed from assertion rows on every read.
 *
 * DB-free contract tests pin the migration shape, concentrating on the guarantees the ticket's
 * acceptance criteria turn into schema rules rather than habits:
 *
 *   * a report is **write-once**, via the same shared trigger the V212 evidence tables use, so
 *     nothing can turn a red deployment green after the fact;
 *   * a report can never summarise another tenant's run — the foreign key is composite against
 *     `verification_run (id, tenant_id)` — and never outlives the run it cites;
 *   * one report per run: a second verdict on the same evidence is not a thing;
 *   * coverage and the verdict are **columns**, because CTG-4.4 (scheduling) and CTG-4.5 (deploy
 *     gating) read them on every check;
 *   * the coverage denominator is honest: `operations_total` counts what the specification
 *     declares, `operations_uncompiled` counts what the compiler could not express, and exercised
 *     can never exceed total.
 *
 * There is deliberately **no new RBAC resource**: a conformance report is verification evidence,
 * governed by V212's `verification_evidence`. The negative assertions below keep it that way.
 *
 * These must stay in lock-step with apiome-rest's `app.provider_verification` contract
 * (`ConformanceReport`, `CoverageSummary`) and its
 * `tests/test_provider_verification_migration.py` sibling.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V252__provider_verification_report_ctg_4_3.sql";
const TABLE = "provider_verification_report";

/** The closed verdict vocabulary. `cancelled` is a *run* state, never a report's. */
const OUTCOMES = ["passed", "failed", "errored"] as const;

/** The coverage columns CTG-4.4 and CTG-4.5 read without opening a report body. */
const COVERAGE_COLUMNS = [
  "operations_total",
  "operations_exercised",
  "operations_passed",
  "operations_failed",
  "operations_errored",
  "operations_skipped",
  "operations_uncompiled",
  "coverage_percent",
  "cases_total",
  "cases_passed",
  "cases_failed",
  "cases_errored",
  "cases_skipped",
  "drift_count",
] as const;

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("provider verification report migration", () => {
  it("is present in scripts/ and ordered after the evidence tables it hangs off", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V212__verification_evidence_4731.sql"),
    );
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V251__consumer_contract_registry_4479.sql"),
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

  describe("a report cannot escape its tenant or outlive its evidence", () => {
    it("scopes the row to a tenant that cascades", () => {
      expect(lower).toContain("tenant_id uuid not null references tenants(id) on delete cascade");
    });

    it("ties the run to the same tenant through a composite foreign key", () => {
      expect(lower).toContain("foreign key (run_id, tenant_id)");
      expect(lower).toContain("references verification_run (id, tenant_id)");
    });

    it("keeps at most one report per run", () => {
      expect(lower).toContain(
        `create unique index if not exists idx_${TABLE}_run`,
      );
    });
  });

  describe("a report is write-once", () => {
    it("installs the shared row-mutation guard as a BEFORE UPDATE trigger", () => {
      expect(lower).toContain(`create trigger trigger_${TABLE}_immutable`);
      expect(lower).toContain(`before update on ${TABLE}`);
      expect(lower).toContain("execute function mcp_forbid_row_mutation();");
    });

    it("never writes an UPDATE of its own", () => {
      expect(lower).not.toContain(`update apiome.${TABLE}`);
    });
  });

  describe("the verdict and the coverage are queryable columns", () => {
    it("admits only the three verdicts a report can carry", () => {
      for (const outcome of OUTCOMES) {
        expect(lower).toContain(`'${outcome}'`);
      }
      expect(lower).toMatch(/check \(outcome in \('passed', 'failed', 'errored'\)\)/);
      // `cancelled` describes a run that was stopped; no set of case records implies it, and a
      // report is only ever derived from case records.
      expect(lower).not.toContain("'cancelled'");
    });

    it("stores every coverage number as its own column", () => {
      for (const column of COVERAGE_COLUMNS) {
        expect(lower).toContain(column);
      }
    });

    it("keeps coverage inside its own bounds", () => {
      expect(lower).toContain("check (coverage_percent >= 0 and coverage_percent <= 100)");
      expect(lower).toContain("check (operations_exercised <= operations_total)");
    });

    it("still stores the whole report, and never as null", () => {
      expect(lower).toContain("report jsonb not null");
    });
  });

  describe("the reads CTG-4.4 and CTG-4.5 make are indexed", () => {
    it("indexes a version's history newest-first", () => {
      expect(lower).toContain(
        `on ${TABLE} (tenant_id, version_ref, created_at desc)`,
      );
    });

    it("indexes one deployment's history", () => {
      expect(lower).toContain(`on ${TABLE} (tenant_id, target_id, created_at desc)`);
    });

    it("keeps a partial index over what is currently drifting", () => {
      expect(lower).toContain("where outcome <> 'passed'");
    });
  });

  describe("the target is a snapshot, not a live reference", () => {
    it("keeps the report readable after the target definition is deleted", () => {
      expect(lower).toContain(
        "target_id uuid references verification_target(id) on delete set null",
      );
    });

    it("stores the identity the run actually used", () => {
      expect(lower).toContain("target_slug");
      expect(lower).toContain("target_environment");
      expect(lower).toContain("target_network_class");
      expect(lower).toContain("target_base_url text not null");
    });
  });

  describe("storage is bounded by age, like the evidence it accompanies", () => {
    it("ships a retention sweep", () => {
      expect(lower).toContain(
        "create or replace function purge_provider_verification_reports(",
      );
      expect(lower).toContain("p_retention_days integer default 365");
    });
  });

  describe("no new RBAC resource", () => {
    it("does not redefine the built-in role grid", () => {
      expect(lower).not.toContain("create or replace function apiome.seed_builtin_roles");
      expect(lower).not.toContain("perform apiome.seed_builtin_roles");
      expect(lower).not.toContain("insert into apiome.role_permissions");
    });

    it("says so, so the next reader does not add one by reflex", () => {
      expect(sql).toContain("verification_evidence");
    });
  });
});
