/**
 * Structural assertions over the style-guide data model migration (#4427, GOV-1.1).
 *
 * V159 adds `apiome.style_guides`, `apiome.style_guide_rules`, and
 * `apiome.style_guide_assignments`, plus the idempotent `seed_builtin_style_guide(tenant)`
 * function that (re)creates the read-only "Apiome Recommended" guide mirroring the linter's
 * shipped rule set — so existing scores don't change on upgrade.
 *
 * DB-free contract tests pin the migration shape: tables, FKs and their cascade behavior,
 * check constraints, uniqueness rules, the seed function, and the exact builtin rule
 * catalog (ids + severities) the seed writes.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V159__style_guides_4427.sql";

/**
 * The canonical builtin rule catalog the seed must mirror, exactly as the linter ships it:
 * apiome-rest `schema_lint.RULE_CATALOGUE` plus the CommonRulePack and the GraphQL /
 * AsyncAPI / protobuf / Arazzo rule packs. `arzzo.unresolvable-operation-ref` is the
 * rule_id exactly as the code emits it (typo included) — ids are stable identifiers.
 */
const BUILTIN_RULES: ReadonlyArray<[ruleId: string, severity: string]> = [
  // OpenAPI / JSON-Schema (schema_lint.RULE_CATALOGUE)
  ["naming.schema-pascal-case", "warning"],
  ["naming.property-name", "warning"],
  ["documentation.schema-missing-description", "warning"],
  ["documentation.property-missing-description", "info"],
  ["documentation.property-missing-example", "info"],
  ["documentation.operation-missing-summary", "warning"],
  ["documentation.info-missing-description", "info"],
  ["structure.unbounded-array", "warning"],
  ["compatibility.breaking", "error"],
  ["compatibility.unknown", "warning"],
  // Cross-format canonical-model pack (lint_engine.CommonRulePack)
  ["common.api-missing-description", "info"],
  ["common.type-missing-description", "warning"],
  ["common.field-missing-description", "info"],
  ["common.operation-missing-description", "warning"],
  ["common.message-missing-description", "info"],
  ["common.channel-missing-description", "info"],
  ["common.unstable-type-name", "warning"],
  ["common.unstable-field-name", "warning"],
  // GraphQL pack (graphql_lint)
  ["graphql.naming-type-pascal-case", "warning"],
  ["graphql.naming-field-camel-case", "warning"],
  ["graphql.naming-argument-camel-case", "warning"],
  ["graphql.naming-enum-value-upper-case", "warning"],
  ["graphql.enum-value-missing-description", "info"],
  ["graphql.argument-missing-description", "info"],
  ["graphql.require-deprecation-reason", "warning"],
  // AsyncAPI pack (asyncapi_lint)
  ["asyncapi.message-missing-name", "info"],
  ["asyncapi.message-unstable-name", "warning"],
  ["asyncapi.message-missing-payload", "warning"],
  ["asyncapi.server-missing-protocol", "warning"],
  ["asyncapi.server-missing-security", "info"],
  // protobuf pack (proto_lint)
  ["protobuf.package-version-suffix", "warning"],
  ["protobuf.field-no-required", "warning"],
  ["protobuf.reserved-on-deletion", "info"],
  // Arazzo pack (arazzo_lint)
  ["arazzo.dangling-operation-id", "error"],
  ["arzzo.unresolvable-operation-ref", "error"],
  ["arazzo.unused-workflow-input", "warning"],
  ["arazzo.missing-success-criteria", "warning"],
];

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("style-guide data model migration", () => {
  it("is present in scripts/ and ordered after V158", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V158__async_job_store_shared_status.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates all three tables idempotently", () => {
    expect(lower).toMatch(/create table if not exists style_guides/);
    expect(lower).toMatch(/create table if not exists style_guide_rules/);
    expect(lower).toMatch(/create table if not exists style_guide_assignments/);
  });

  describe("style_guides", () => {
    it("is tenant-scoped with cascade delete", () => {
      expect(lower).toMatch(
        /style_guides[\s\S]*?tenant_id\s+uuid\s+not null references tenants\(id\) on delete cascade/,
      );
    });

    it("constrains source to builtin | custom, defaulting to custom", () => {
      expect(lower).toMatch(/default 'custom'/);
      expect(lower).toMatch(
        /style_guides_source_ck check \(source in \('builtin', 'custom'\)\)/,
      );
    });

    it("keeps guide names unique per tenant", () => {
      expect(lower).toMatch(
        /style_guides_tenant_name_uq unique \(tenant_id, name\)/,
      );
    });

    it("allows at most one default and one builtin guide per tenant", () => {
      expect(lower).toMatch(
        /create unique index if not exists style_guides_one_default_per_tenant\s+on style_guides \(tenant_id\) where is_default/,
      );
      expect(lower).toMatch(
        /create unique index if not exists style_guides_one_builtin_per_tenant\s+on style_guides \(tenant_id\) where source = 'builtin'/,
      );
    });
  });

  describe("style_guide_rules", () => {
    it("belongs to a guide with cascade delete", () => {
      expect(lower).toMatch(
        /style_guide_rules[\s\S]*?guide_id\s+uuid\s+not null references style_guides\(id\) on delete cascade/,
      );
    });

    it("constrains severity to the linter's vocabulary (error | warning | info)", () => {
      expect(lower).toMatch(
        /style_guide_rules_severity_ck check \(severity in \('error', 'warning', 'info'\)\)/,
      );
    });

    it("defaults enabled to true and stores custom definitions as jsonb", () => {
      expect(lower).toMatch(/enabled\s+boolean not null default true/);
      expect(lower).toMatch(/custom_def\s+jsonb/);
    });

    it("keeps rule ids unique within a guide", () => {
      expect(lower).toMatch(
        /style_guide_rules_guide_rule_uq unique \(guide_id, rule_id\)/,
      );
    });
  });

  describe("style_guide_assignments", () => {
    it("belongs to a guide with cascade delete", () => {
      expect(lower).toMatch(
        /style_guide_assignments[\s\S]*?guide_id\s+uuid\s+not null references style_guides\(id\) on delete cascade/,
      );
    });

    it("references tenants and projects with cascade delete", () => {
      expect(lower).toMatch(
        /style_guide_assignments[\s\S]*?tenant_id\s+uuid\s+references tenants\(id\) on delete cascade/,
      );
      expect(lower).toMatch(
        /style_guide_assignments[\s\S]*?project_id\s+uuid\s+references projects\(id\) on delete cascade/,
      );
    });

    it("requires exactly one of tenant_id / project_id", () => {
      expect(lower).toMatch(
        /style_guide_assignments_target_ck[\s\S]*?check \(\(tenant_id is null\) <> \(project_id is null\)\)/,
      );
    });

    it("allows one tenant-wide assignment per tenant and one per project", () => {
      expect(lower).toMatch(
        /style_guide_assignments_tenant_uq\s+on style_guide_assignments \(tenant_id\) where tenant_id is not null/,
      );
      expect(lower).toMatch(
        /style_guide_assignments_project_uq\s+on style_guide_assignments \(project_id\) where project_id is not null/,
      );
    });
  });

  describe('"Apiome Recommended" builtin seed', () => {
    it("defines the idempotent per-tenant seed function", () => {
      expect(lower).toMatch(
        /create or replace function apiome\.seed_builtin_style_guide\(p_tenant uuid\)/,
      );
      expect(sql).toContain("'Apiome Recommended'");
      expect(lower).toContain("'builtin'");
    });

    it("rewrites the builtin rule rows from scratch (self-healing)", () => {
      expect(lower).toMatch(
        /delete from apiome\.style_guide_rules where guide_id = v_guide/,
      );
    });

    it("never steals default status from a guide the tenant chose", () => {
      expect(lower).toMatch(
        /not exists \(select 1 from apiome\.style_guides where tenant_id = p_tenant and is_default\)/,
      );
    });

    it("seeds every existing tenant", () => {
      expect(lower).toMatch(/for t in select id from apiome\.tenants loop/);
      expect(lower).toMatch(/perform apiome\.seed_builtin_style_guide\(t\.id\)/);
    });

    it(`mirrors the linter's shipped catalog: all ${BUILTIN_RULES.length} rule ids at their code-constant severities`, () => {
      for (const [ruleId, severity] of BUILTIN_RULES) {
        // Each catalog row appears as ('<rule_id>', '<severity>') in the seed VALUES list.
        const row = new RegExp(
          `\\('${ruleId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}',\\s*'${severity}'\\)`,
        );
        expect(lower).toMatch(row);
      }
    });

    it("seeds exactly the canonical catalog — no extra rules", () => {
      const seeded = [...lower.matchAll(/\('([a-z0-9.-]+)',\s*'(error|warning|info)'\)/g)].map(
        (m) => m[1],
      );
      expect(new Set(seeded).size).toBe(seeded.length);
      expect(seeded.sort()).toEqual(BUILTIN_RULES.map(([id]) => id).sort());
    });
  });
});
