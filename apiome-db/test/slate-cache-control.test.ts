/**
 * Structural assertions over the Slate cache control migration (UXE-3.1, private-suite#2473).
 *
 * V187 adds the cache control plane: per-environment presets, expert route rules, deterministic
 * trace evidence, scoped purge records and an append-only audit.
 *
 * The suite is DB-free — this package asserts migration SQL structurally, and application
 * against a live database is proven in apiome-rest — so these tests pin the migration's
 * contract. They are weighted toward the claims the schema is what makes true:
 *
 *   1. presets are CHECK-enumerated and bypass cannot exist without an expiry;
 *   2. rule precedence is a total order, so a trace is reproducible;
 *   3. a purge record carries its scope, its estimate and the basis of that estimate;
 *   4. nothing can be recorded as dispatched on a lane with no delivery tier attached.
 *
 * The last is the honesty rule. A guarantee that lives only in the service layer survives
 * exactly as long as the next caller behaves, so it is asserted here as a CHECK constraint
 * rather than as documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V187__slate_cache_control_2473.sql";

/** Every table the cache control plane introduces. */
const TABLES = [
  "slate_cache_policies",
  "slate_cache_rules",
  "slate_cache_rule_tags",
  "slate_cache_traces",
  "slate_cache_purges",
  "slate_cache_audit",
] as const;

/**
 * Tables that carry a denormalized tenant_id, per the repo's tenancy convention.
 * `slate_cache_rule_tags` is excluded deliberately: it is reachable only through a rule, which
 * is itself tenant-scoped, so a second copy would be a fact that can disagree with itself.
 */
const TENANT_SCOPED = [
  "slate_cache_policies",
  "slate_cache_rules",
  "slate_cache_traces",
  "slate_cache_purges",
  "slate_cache_audit",
] as const;

let sql = "";
let lower = "";

/** Extract a single `CREATE TABLE ... (...);` body so column assertions cannot match a neighbour. */
function tableBody(table: string): string {
  const start = sql.indexOf(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
  if (start === -1) throw new Error(`table ${table} not found in ${MIGRATION}`);
  const end = sql.indexOf("\n);", start);
  if (end === -1) throw new Error(`unterminated CREATE TABLE for ${table}`);
  return sql.slice(start, end);
}

/**
 * Column names declared by a `CREATE TABLE` body, ignoring inline comments, CHECK continuation
 * lines and table-level constraints. Used to prove every column is documented.
 */
function columnNames(table: string): string[] {
  const body = tableBody(table);
  const lines = body.split("\n").slice(1);
  const names: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "" || trimmed.startsWith("--")) continue;
    const match = /^([a-z_]+)\s+(UUID|TEXT|INTEGER|BIGINT|BOOLEAN|JSONB|TIMESTAMP)/.exec(trimmed);
    if (match) names.push(match[1]);
  }
  return names;
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Slate cache control migration", () => {
  it("is present in scripts/ and ordered after V186", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V186__slate_managed_hosting_2456.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates every cache control-plane table idempotently", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
    }
  });

  it("names the ticket so the schema is traceable to its rationale", () => {
    expect(sql).toContain("UXE-3.1");
    expect(sql).toContain("private-suite#2473");
  });

  /* ---------------------------------------------------------------------- */
  /* Tenancy                                                                */
  /* ---------------------------------------------------------------------- */

  it("scopes every top-level table to a tenant and cascades deletion", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
      );
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 1 — presets are documented and deterministic                 */
  /* ---------------------------------------------------------------------- */

  it("enumerates exactly the four roadmap presets, so an unknown one cannot be stored", () => {
    expect(tableBody("slate_cache_policies")).toContain(
      "CHECK (preset IN ('standard', 'aggressive', 'bypass', 'personalized'))",
    );
  });

  it("refuses a bypass preset with no expiry, so an incident mode cannot become the config", () => {
    expect(sql).toContain("slate_cache_policies_bypass_needs_expiry");
    expect(sql).toContain("CHECK (preset <> 'bypass' OR preset_expires_at IS NOT NULL)");
  });

  it("gives a lane exactly one cache policy", () => {
    expect(tableBody("slate_cache_policies")).toMatch(/environment_id\s+UUID NOT NULL UNIQUE/);
  });

  it("keeps preset overrides apart from the preset name", () => {
    const body = tableBody("slate_cache_policies");
    expect(body).toMatch(/preset_overrides\s+JSONB NOT NULL/);
    expect(body).toMatch(/preset\s+TEXT NOT NULL/);
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 2 — deterministic evaluation                                 */
  /* ---------------------------------------------------------------------- */

  it("makes rule precedence a total order rather than a set with ties", () => {
    expect(tableBody("slate_cache_rules")).toContain("UNIQUE (environment_id, ordinal)");
  });

  it("carries every expert-rule field the roadmap names", () => {
    const body = tableBody("slate_cache_rules");
    for (const column of [
      "matcher_kind",
      "matcher_value",
      "matcher_methods",
      "matcher_hosts",
      "eligibility",
      "browser_ttl_seconds",
      "edge_ttl_seconds",
      "stale_while_revalidate_seconds",
      "stale_if_error_seconds",
      "cache_key_base",
      "vary_query_mode",
      "vary_query_keys",
      "vary_headers",
      "vary_cookies",
      "bypass_conditions",
    ]) {
      expect(body).toContain(column);
    }
  });

  it("defaults rule methods to GET and HEAD, because caching a mutating method is a bug", () => {
    expect(tableBody("slate_cache_rules")).toContain("DEFAULT ARRAY['GET', 'HEAD']::TEXT[]");
  });

  it("retains a disabled rule rather than deleting it, so a trace can explain the silence", () => {
    expect(tableBody("slate_cache_rules")).toMatch(/enabled\s+BOOLEAN NOT NULL DEFAULT TRUE/);
  });

  it("constrains the trace rules digest to the sha256 form rather than any string", () => {
    expect(tableBody("slate_cache_traces")).toMatch(
      /rules_digest[^,]*\^sha256:\[0-9a-f\]\{64\}\$/,
    );
  });

  it("records which policy generation answered a trace", () => {
    expect(tableBody("slate_cache_traces")).toMatch(/policy_version\s+BIGINT NOT NULL/);
  });

  it("allows a trace with no winning rule, because the preset default deciding is an answer", () => {
    const body = tableBody("slate_cache_traces");
    expect(body).toMatch(/winning_rule_id\s+UUID REFERENCES/);
    expect(body).not.toMatch(/winning_rule_id\s+UUID NOT NULL/);
  });

  it("gives cache policy an optimistic-concurrency token, as routing has", () => {
    expect(tableBody("slate_cache_policies")).toMatch(/policy_version\s+BIGINT NOT NULL DEFAULT 0/);
  });

  /* ---------------------------------------------------------------------- */
  /* Criterion 3 — purge scope, estimate and audit                          */
  /* ---------------------------------------------------------------------- */

  it("enumerates exactly the five roadmap purge scopes", () => {
    expect(tableBody("slate_cache_purges")).toContain(
      "CHECK (scope_kind IN ('release', 'tag', 'prefix', 'host', 'url'))",
    );
  });

  it("requires an estimate and the basis that produced it", () => {
    const body = tableBody("slate_cache_purges");
    expect(body).toMatch(/estimated_objects\s+INTEGER NOT NULL CHECK \(estimated_objects >= 0\)/);
    expect(body).toMatch(/estimate_basis\s+TEXT NOT NULL/);
  });

  it("requires a stated reason, so a purge can be explained afterwards", () => {
    expect(tableBody("slate_cache_purges")).toMatch(/reason\s+TEXT NOT NULL/);
  });

  it("records the basis release for every scope, not only release scope", () => {
    expect(tableBody("slate_cache_purges")).toMatch(/release_id\s+UUID REFERENCES/);
  });

  it("pairs a refusal with its reason and forbids a reason without one", () => {
    expect(sql).toContain("slate_cache_purges_refusal_has_reason");
    expect(sql).toContain("CHECK ((outcome = 'refused') = (refusal_reason IS NOT NULL))");
  });

  it("normalizes rule tags, because purge-by-tag is a join", () => {
    expect(tableBody("slate_cache_rule_tags")).toContain("UNIQUE (rule_id, tag)");
    expect(sql).toContain("CREATE INDEX IF NOT EXISTS idx_slate_cache_rule_tags_tag");
  });

  it("refuses UPDATE and DELETE on the cache audit at the database", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_cache_audit_append_only()");
    expect(sql).toContain("BEFORE UPDATE OR DELETE ON apiome.slate_cache_audit");
    expect(sql).toContain("is append-only: % is not permitted");
  });

  it("scopes audit entries to what they are about", () => {
    expect(tableBody("slate_cache_audit")).toContain(
      "CHECK (subject_kind IN ('preset', 'rule', 'purge', 'trace'))",
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Honesty — nothing may claim a flush that did not happen                */
  /* ---------------------------------------------------------------------- */

  it("forbids recording a dispatched purge on a lane with no delivery tier", () => {
    expect(sql).toContain("slate_cache_purges_dispatch_needs_edge");
    expect(sql).toContain("CHECK (outcome <> 'dispatched' OR edge_attached)");
  });

  it("defaults edge_attached to FALSE on both the policy and the purge record", () => {
    expect(tableBody("slate_cache_policies")).toMatch(
      /edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
    expect(tableBody("slate_cache_purges")).toMatch(
      /edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
  });

  it("snapshots edge_attached onto the purge rather than joining it live", () => {
    // Denormalized deliberately: attaching an edge later must not make old records, written
    // when nothing was attached, retroactively look like flushes.
    expect(tableBody("slate_cache_purges")).toContain("edge_attached");
  });

  it("states the scope boundary in prose, as V186 did", () => {
    expect(sql).toContain("Scope boundary, stated plainly.");
    expect(sql).toContain("there is nothing to evict");
  });

  /* ---------------------------------------------------------------------- */
  /* House rule — every column is documented                                */
  /* ---------------------------------------------------------------------- */

  it("comments every table", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`COMMENT ON TABLE apiome.${table} IS`);
    }
  });

  it("comments every column of every table", () => {
    for (const table of TABLES) {
      for (const column of columnNames(table)) {
        if (column === "id") continue; // The surrogate key is self-describing.
        expect(sql).toContain(`COMMENT ON COLUMN apiome.${table}.${column} IS`);
      }
    }
  });
});
