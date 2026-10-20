/**
 * Structural assertions over the agent-pack style-guide re-seed migration (#3974 / #3975).
 *
 * V246 re-seeded "Apiome Recommended" from the full rule registry because
 * `CompiledStyleGuide.apply` drops a finding whose rule is registered but absent from the
 * guide. The A2A Agent Card pack (MFI-18.1) shipped without extending that list; V304 adds it
 * and the ACP agent-manifest pack (MFI-18.2). These DB-free tests pin that every rule of both
 * packs is seeded at its pack's severity and that the V246 list survives; the authoritative
 * "seed equals live registry" check is `apiome-rest/tests/test_data_contract_lint.py`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V304__style_guide_builtin_reseed_agent_packs_3975.sql";
const PREVIOUS = "V246__style_guide_builtin_reseed_5443.sql";

/** The agent-descriptor rules this migration adds, at the severity their pack declares. */
const AGENT_PACK_RULES: ReadonlyArray<[ruleId: string, severity: string]> = [
  ["a2a.apikey-in-query", "warning"],
  ["a2a.duplicate-skill-id", "error"],
  ["a2a.insecure-endpoint", "warning"],
  ["a2a.missing-required-field", "warning"],
  ["a2a.no-security", "warning"],
  ["a2a.security-undeclared-scheme", "error"],
  ["a2a.skill-missing-description", "warning"],
  ["a2a.skill-missing-tags", "info"],
  ["a2a.skill-without-modes", "info"],
  ["a2a.unknown-scheme-type", "warning"],
  ["acp.agent-missing-description", "warning"],
  ["acp.capability-missing-description", "warning"],
  ["acp.duplicate-agent-name", "error"],
  ["acp.duplicate-capability-name", "warning"],
  ["acp.invalid-agent-name", "warning"],
  ["acp.missing-license", "info"],
  ["acp.missing-tags", "info"],
  ["acp.no-capabilities", "info"],
  ["acp.untyped-content", "info"],
];

/** Every `(rule, severity)` row a seed script lists. */
function seededRows(sql: string): string[] {
  return [...sql.matchAll(/\('([A-Za-z0-9.\-]+)',\s*'(error|warning|info)'\)/g)].map(
    (m) => `${m[1]}=${m[2]}`,
  );
}

describe(`${MIGRATION} — agent-pack style-guide re-seed`, () => {
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

  it("replaces the seed function and re-seeds every tenant", () => {
    const lower = sql.toLowerCase();
    expect(lower).toMatch(/create or replace function apiome\.seed_builtin_style_guide\(p_tenant uuid\)/);
    expect(lower).toMatch(/for t in select id from apiome\.tenants loop/);
    expect(lower).toMatch(/where tenant_id = p_tenant and source = 'builtin'/);
  });

  it.each(AGENT_PACK_RULES)("seeds %s at %s", (ruleId, severity) => {
    expect(seededRows(sql)).toContain(`${ruleId}=${severity}`);
  });

  it("keeps every rule V246 seeded, at the same severity", () => {
    const now = new Set(seededRows(sql));
    for (const row of seededRows(previous)) expect(now.has(row)).toBe(true);
  });

  it("seeds every rule exactly once", () => {
    const ids = seededRows(sql).map((row) => row.split("=")[0]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBe(seededRows(previous).length + AGENT_PACK_RULES.length);
  });
});
