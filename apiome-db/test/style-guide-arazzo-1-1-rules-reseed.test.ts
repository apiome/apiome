/**
 * Structural assertions over the Arazzo 1.1 rules style-guide re-seed migration (#5879, GVM-4.4).
 *
 * `CompiledStyleGuide.apply` drops a finding whose rule is registered but absent from the
 * "Apiome Recommended" guide, so the twelve Arazzo 1.1 validation rules must be seeded. V400 adds
 * them to the V399 list and seeds the operationRef rule under its corrected id,
 * `arazzo.unresolvable-operation-ref`, in place of the shipped typo `arzzo.unresolvable-operation-ref`
 * (which stays a registered alias in apiome-rest). These DB-free tests pin that every new rule is
 * seeded at its severity, that the rename is the only change to the V399 rows, and that the
 * migration keeps the seed function's shape; the authoritative "seed equals live registry" check
 * is `apiome-rest/tests/test_data_contract_lint.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V400__style_guide_builtin_reseed_arazzo_1_1_rules_5879.sql";
const PREVIOUS = "V399__style_guide_builtin_reseed_openapi_fix_rules_5869.sql";

/** The Arazzo 1.1 rules this migration adds, at the severity their pack declares. */
const ARAZZO_1_1_RULES: ReadonlyArray<[ruleId: string, severity: string]> = [
  ["arazzo.runtime-expression-invalid", "error"],
  ["arazzo.success-criteria-context-required", "error"],
  ["arazzo.on-success-target-unresolved", "error"],
  ["arazzo.on-failure-target-unresolved", "error"],
  ["arazzo.component-ref-unresolved", "error"],
  ["arazzo.step-id-duplicate", "error"],
  ["arazzo.workflow-id-duplicate", "error"],
  ["arazzo.depends-on-cycle", "error"],
  ["arazzo.parameter-in-invalid", "error"],
  ["arazzo.inputs-schema-invalid", "error"],
  ["arazzo.outputs-expression-invalid", "error"],
  ["arazzo.source-description-type-invalid", "error"],
];

/** The shipped (typo) id and the id it is seeded under now. */
const LEGACY_ID = "arzzo.unresolvable-operation-ref";
const CANONICAL_ID = "arazzo.unresolvable-operation-ref";

/** Every `(rule, severity)` row a seed script lists. */
function seededRows(sql: string): string[] {
  return [...sql.matchAll(/\('([A-Za-z0-9.\-]+)',\s*'(error|warning|info)'\)/g)].map(
    (m) => `${m[1]}=${m[2]}`,
  );
}

describe(`${MIGRATION} — Arazzo 1.1 rules style-guide re-seed`, () => {
  let sql = "";
  let previous = "";

  beforeAll(async () => {
    sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
    previous = await fs.readFile(path.join(SCRIPTS_DIR, PREVIOUS), "utf8");
  });

  it("is registered in the migration sequence", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const names = files.map((f) => (typeof f === "string" ? f : f.name ?? f.file ?? ""));
    expect(names.some((name) => String(name).endsWith(MIGRATION))).toBe(true);
  });

  it("replaces the seed function, rewrites only the builtin guide and re-seeds every tenant", () => {
    const lower = sql.toLowerCase();
    expect(lower).toMatch(/create or replace function apiome\.seed_builtin_style_guide\(p_tenant uuid\)/);
    expect(lower).toMatch(/delete from apiome\.style_guide_rules where guide_id = v_guide/);
    expect(lower).toMatch(/where tenant_id = p_tenant and source = 'builtin'/);
    expect(lower).toMatch(/for t in select id from apiome\.tenants loop/);
  });

  it.each(ARAZZO_1_1_RULES)("seeds %s at %s", (ruleId, severity) => {
    expect(seededRows(sql)).toContain(`${ruleId}=${severity}`);
  });

  it("seeds the operationRef rule under its corrected id, not the typo", () => {
    const rows = seededRows(sql);
    expect(rows).toContain(`${CANONICAL_ID}=error`);
    expect(rows.some((row) => row.startsWith(`${LEGACY_ID}=`))).toBe(false);
  });

  it("keeps every other rule V399 seeded, at the same severity", () => {
    const now = new Set(seededRows(sql));
    for (const row of seededRows(previous)) {
      if (row.startsWith(`${LEGACY_ID}=`)) continue;
      expect(now.has(row)).toBe(true);
    }
  });

  it("seeds every rule exactly once", () => {
    const ids = seededRows(sql).map((row) => row.split("=")[0]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBe(seededRows(previous).length + ARAZZO_1_1_RULES.length);
  });
});
