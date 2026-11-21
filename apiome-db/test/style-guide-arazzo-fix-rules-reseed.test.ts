/**
 * Structural assertions over the fixable Arazzo rules style-guide re-seed migration (#5880, GVM-4.5).
 *
 * `CompiledStyleGuide.apply` drops a finding whose rule is registered but absent from the
 * "Apiome Recommended" guide, so the three on-demand Arazzo fix rules must be seeded. V401 adds
 * them to the V400 list. These DB-free tests pin each rule at its severity and that nothing else
 * changed; the authoritative "seed equals live registry" check is
 * `apiome-rest/tests/test_data_contract_lint.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V401__style_guide_builtin_reseed_arazzo_fix_rules_5880.sql";
const PREVIOUS = "V400__style_guide_builtin_reseed_arazzo_1_1_rules_5879.sql";

/** The fixable Arazzo rules this migration adds, at the severity app.arazzo_fix_rules declares. */
const ARAZZO_FIX_RULES: ReadonlyArray<[ruleId: string, severity: string]> = [
  ["arazzo.step-id-suffix", "warning"],
  ["arazzo.success-criteria-scaffold", "warning"],
  ["arazzo.version-marker-bump", "warning"],
];

/** Every `(rule, severity)` row a seed script lists. */
function seededRows(sql: string): string[] {
  return [...sql.matchAll(/\('([A-Za-z0-9.\-]+)',\s*'(error|warning|info)'\)/g)].map(
    (m) => `${m[1]}=${m[2]}`,
  );
}

describe(`${MIGRATION} — fixable Arazzo rules style-guide re-seed`, () => {
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

  it.each(ARAZZO_FIX_RULES)("seeds %s at %s", (ruleId, severity) => {
    expect(seededRows(sql)).toContain(`${ruleId}=${severity}`);
  });

  it("keeps every rule V400 seeded, at the same severity", () => {
    const now = new Set(seededRows(sql));
    for (const row of seededRows(previous)) expect(now.has(row)).toBe(true);
  });

  it("seeds every rule exactly once", () => {
    const ids = seededRows(sql).map((row) => row.split("=")[0]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBe(seededRows(previous).length + ARAZZO_FIX_RULES.length);
  });
});
