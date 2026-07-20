/**
 * Structural assertions over the Slate security control migration (UXE-3.2, private-suite#2474).
 *
 * V188 adds the security control plane: per-environment policy, managed WAF group modes, custom
 * rules with an explicit precedence and a staged rollout, revision history, expiring exceptions,
 * dual-control approvals, redacted security events and an append-only audit.
 *
 * The suite is DB-free — this package asserts migration SQL structurally, and application against
 * a live database is proven in apiome-rest — so these tests pin the migration's contract. They are
 * weighted toward the claims the schema is what makes true:
 *
 *   1. the author cannot approve their own change, and one approver cannot approve twice;
 *   2. evidence is redacted by allowlist, so the field nobody thought of fails closed;
 *   3. nothing may be recorded as observed or mitigated on a lane with no delivery tier;
 *   4. every exception expires, so a carve-out cannot quietly become the policy;
 *   5. rule precedence is a total order, so a simulation is reproducible;
 *   6. revision history outlives the rule it describes, so a delete is still revertible.
 *
 * The third is the honesty rule, and it matters more here than it did for cache. An unenforced
 * cache rule wastes a purge; an unenforced WAF rule means somebody believes they are stopping an
 * attacker and is not. A guarantee that lives only in the service layer survives exactly as long
 * as the next caller behaves, so it is asserted here as a CHECK constraint rather than as
 * documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V188__slate_security_control_2474.sql";

/** Every table the security control plane introduces. */
const TABLES = [
  "slate_security_policies",
  "slate_security_managed_groups",
  "slate_security_rules",
  "slate_security_rule_revisions",
  "slate_security_exceptions",
  "slate_security_approvals",
  "slate_security_events",
  "slate_security_audit",
] as const;

/**
 * Tables that carry a denormalized tenant_id, per the repo's tenancy convention. Unlike the cache
 * plane's rule_tags, every table here is one — including `slate_security_rule_revisions`, which
 * cannot reach a tenant through its rule because that rule may already be gone.
 */
const TENANT_SCOPED = TABLES;

/** Header keys that must never be storable as event evidence, whatever the allowlist grows to. */
const FORBIDDEN_EVIDENCE_KEYS = ["cookie", "authorization", "body", "headers"] as const;

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

/**
 * The expression of a named table-level CHECK constraint, with comments and newlines collapsed.
 *
 * Several claims in this suite are negative — "the distinctness CHECK does NOT name the nullable
 * user ids". Asserting those by `not.toContain("<some exact literal>")` is fragile in the worst
 * way: it passes whether the migration is correct or merely formatted differently, so a reformat
 * would leave the test green while it proved nothing. Reading the real expression out and
 * inspecting what it names keeps the assertion semantic.
 *
 * @param body - A `CREATE TABLE` body from `tableBody`.
 * @param name - The constraint name to extract.
 * @returns The constraint expression text.
 */
function constraintExpression(body: string, name: string): string {
  const start = body.indexOf(`CONSTRAINT ${name}`);
  if (start === -1) throw new Error(`constraint ${name} not found`);
  const rest = body.slice(start);
  const open = rest.indexOf("(");
  if (open === -1) throw new Error(`constraint ${name} has no expression`);
  let depth = 0;
  for (let i = open; i < rest.length; i += 1) {
    if (rest[i] === "(") depth += 1;
    else if (rest[i] === ")") {
      depth -= 1;
      if (depth === 0) {
        return rest
          .slice(open, i + 1)
          .replace(/--[^\n]*/g, "")
          .replace(/\s+/g, " ");
      }
    }
  }
  throw new Error(`constraint ${name} is unterminated`);
}

/**
 * The table-level `UNIQUE (...)` clause of a `CREATE TABLE` body.
 *
 * Same reasoning as `constraintExpression`: read the clause and inspect it, rather than asserting
 * the absence of a literal that may never have been there.
 *
 * @param body - A `CREATE TABLE` body from `tableBody`.
 * @returns The column list inside the UNIQUE clause.
 */
function uniqueClause(body: string): string {
  const match = /\n\s*UNIQUE\s*\(([^)]*)\)/.exec(body);
  if (!match) throw new Error("no table-level UNIQUE clause found");
  return match[1].replace(/\s+/g, " ").trim();
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Slate security control migration", () => {
  it("is present in scripts/ and ordered after V187", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V187__slate_cache_control_2473.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates every security control-plane table idempotently", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
    }
  });

  it("names the ticket so the schema is traceable to its rationale", () => {
    expect(sql).toContain("UXE-3.2");
    expect(sql).toContain("private-suite#2474");
  });

  /* ---------------------------------------------------------------------- */
  /* Tenancy                                                                */
  /* ---------------------------------------------------------------------- */

  it("scopes every security table to a tenant and cascades deletion", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
      );
    }
  });

  it("keeps tenant_id on rule revisions, which cannot reach a tenant through a deleted rule", () => {
    expect(tableBody("slate_security_rule_revisions")).toMatch(
      /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Dual control — the constraint V186's approvals table does not have     */
  /* ---------------------------------------------------------------------- */

  it("forbids an author approving their own change", () => {
    expect(sql).toContain("slate_security_approvals_distinct_actors");
    expect(sql).toContain("CHECK (approver_actor_key <> author_actor_key)");
  });

  it("compares the immutable identity keys, not the nullable user ids", () => {
    // The whole point of the *_key columns. The *_actor_id columns are ON DELETE SET NULL, so a
    // distinctness CHECK over them would turn a genuine two-person approval into two NULLs that
    // no longer look distinct — a constraint that weakens when somebody is offboarded.
    const body = tableBody("slate_security_approvals");
    expect(body).toMatch(/author_actor_key\s+TEXT NOT NULL/);
    expect(body).toMatch(/approver_actor_key\s+TEXT NOT NULL/);
    expect(body).toMatch(/author_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/);
    expect(body).toMatch(
      /approver_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/,
    );
    // Asserted semantically rather than by absence of one exact literal: pull the distinctness
    // CHECK out of the table body and inspect what it actually names. A `not.toContain` on a
    // hand-written string would keep passing if the migration were reformatted, proving less
    // while still looking green.
    const distinctness = constraintExpression(body, "slate_security_approvals_distinct_actors");
    expect(distinctness).toContain("approver_actor_key");
    expect(distinctness).toContain("author_actor_key");
    expect(distinctness).not.toMatch(/_actor_id\b/);
  });

  it("lets one approver approve a given body once, so two clicks are not two approvals", () => {
    expect(tableBody("slate_security_approvals")).toContain(
      "UNIQUE (subject_id, digest, approver_actor_key)",
    );
    // Keyed on the identity string for the same reason: two NULL user ids would be distinct rows
    // under a UNIQUE that named approver_actor_id, so the duplicate would sail through. Read the
    // UNIQUE clause out of the body rather than asserting the absence of a literal, so a
    // reformat cannot quietly turn this into an assertion about nothing.
    const unique = uniqueClause(tableBody("slate_security_approvals"));
    expect(unique).toContain("approver_actor_key");
    expect(unique).not.toMatch(/_actor_id\b/);
  });

  it("content-addresses what was approved, so a stale approval is detectable", () => {
    expect(tableBody("slate_security_approvals")).toMatch(
      /digest\s+TEXT NOT NULL CHECK \(digest ~ '\^sha256:\[0-9a-f\]\{64\}\$'\)/,
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Redaction by allowlist, not denylist                                   */
  /* ---------------------------------------------------------------------- */

  it("constrains event evidence to an allowlist by subset, not by a denylist", () => {
    // `jsonb - text[]` removes every listed key, so the result is empty only when every key
    // present was one of the permitted ones. A denylist fails open on the field nobody thought of.
    expect(sql).toContain("slate_security_events_evidence_allowlisted");
    expect(sql).toMatch(/CHECK \(evidence - ARRAY\[/);
    expect(sql).toMatch(/= '\{\}'::jsonb\)/);
  });

  it("permits exactly the ten redacted evidence keys", () => {
    const body = tableBody("slate_security_events");
    for (const key of [
      "method",
      "path",
      "query",
      "userAgent",
      "country",
      "asn",
      "clientIpPrefix",
      "matchedFragment",
      "statusCode",
      "botClass",
    ]) {
      expect(body).toContain(`'${key}'`);
    }
  });

  it("admits no secret-bearing key into the allowlist", () => {
    const allowlist = /CHECK \(evidence - ARRAY\[([\s\S]*?)\]\s*=\s*'\{\}'::jsonb\)/.exec(sql);
    expect(allowlist).not.toBeNull();
    const keys = allowlist![1].toLowerCase();
    for (const forbidden of FORBIDDEN_EVIDENCE_KEYS) {
      expect(keys).not.toContain(`'${forbidden}'`);
    }
  });

  it("expires captured request data, because evidence is a liability rather than an asset", () => {
    expect(tableBody("slate_security_events")).toMatch(
      /retain_until\s+TIMESTAMP WITH TIME ZONE NOT NULL/,
    );
    expect(sql).toContain("slate_security_events_retention_after_event");
    expect(sql).toContain("CHECK (retain_until > at)");
  });

  /* ---------------------------------------------------------------------- */
  /* Honesty — nothing may claim an observation or a block that did not     */
  /* happen                                                                 */
  /* ---------------------------------------------------------------------- */

  it("forbids claiming a request was stopped on a lane with no delivery tier", () => {
    expect(sql).toContain("slate_security_events_mitigated_needs_edge");
    expect(sql).toContain("CHECK (mitigated = FALSE OR edge_attached)");
  });

  it("forbids recording an edge-observed event with no edge", () => {
    expect(sql).toContain("slate_security_events_observed_needs_edge");
    expect(sql).toContain("CHECK (source <> 'edge-observed' OR edge_attached)");
  });

  it("defaults an event to a simulation that observed and mitigated nothing", () => {
    const body = tableBody("slate_security_events");
    expect(body).toMatch(/source\s+TEXT NOT NULL DEFAULT 'policy-simulation'/);
    expect(body).toMatch(/mitigated\s+BOOLEAN NOT NULL DEFAULT FALSE/);
    expect(body).toMatch(/edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/);
  });

  it("snapshots edge_attached onto the event rather than joining it live", () => {
    // Denormalized deliberately: attaching an edge later must not make old rows, written when
    // nothing was in the request path, retroactively look observed.
    expect(tableBody("slate_security_policies")).toMatch(
      /edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
    expect(tableBody("slate_security_events")).toContain("edge_attached");
  });

  it("states the scope boundary in prose, as V186 and V187 did", () => {
    expect(sql).toContain("Scope boundary, stated plainly");
    expect(sql).toContain("believes they are stopping an attacker and is not");
  });

  /* ---------------------------------------------------------------------- */
  /* Exceptions — every hole lapses                                         */
  /* ---------------------------------------------------------------------- */

  it("requires every exception to expire, so a carve-out cannot become the policy", () => {
    expect(tableBody("slate_security_exceptions")).toMatch(
      /expires_at\s+TIMESTAMP WITH TIME ZONE NOT NULL,/,
    );
    expect(sql).toContain("slate_security_exceptions_expiry_after_creation");
    expect(sql).toContain("CHECK (expires_at > created_at)");
  });

  it("requires a stated reason for every exception", () => {
    expect(tableBody("slate_security_exceptions")).toMatch(/reason\s+TEXT NOT NULL/);
  });

  it("scopes an exception to a subject and a route pattern", () => {
    const body = tableBody("slate_security_exceptions");
    expect(body).toContain("CHECK (subject_kind IN ('managed-group', 'rule', 'policy'))");
    expect(body).toContain("CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex'))");
  });

  /* ---------------------------------------------------------------------- */
  /* Deterministic evaluation                                               */
  /* ---------------------------------------------------------------------- */

  it("makes rule precedence a total order rather than a set with ties", () => {
    expect(tableBody("slate_security_rules")).toContain("UNIQUE (environment_id, ordinal)");
  });

  it("retains a disabled rule rather than deleting it, so a simulation can explain the silence", () => {
    expect(tableBody("slate_security_rules")).toMatch(/enabled\s+BOOLEAN NOT NULL DEFAULT TRUE/);
  });

  it("defaults a rule to simulate at zero percent, so enforcement is a deliberate sequence", () => {
    const body = tableBody("slate_security_rules");
    expect(body).toMatch(/rollout_mode\s+TEXT NOT NULL DEFAULT 'simulate'/);
    expect(body).toContain("CHECK (rollout_mode IN ('simulate', 'enforce'))");
    expect(body).toMatch(/rollout_percent\s+INTEGER NOT NULL DEFAULT 0/);
    expect(body).toContain("CHECK (rollout_percent BETWEEN 0 AND 100)");
  });

  it("ties a rate limit to its budget in both directions", () => {
    expect(sql).toContain("slate_security_rules_rate_needs_budget");
    expect(sql).toContain("CHECK ((action = 'rate-limit')");
  });

  it("enumerates the rule actions, so an unknown action cannot be stored", () => {
    expect(tableBody("slate_security_rules")).toContain(
      "CHECK (action IN ('allow', 'log', 'challenge', 'rate-limit', 'block'))",
    );
  });

  it("uses the same four matcher kinds as the cache rules, so nothing must be relearned", () => {
    expect(tableBody("slate_security_rules")).toContain(
      "CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex'))",
    );
  });

  it("gives security policy an optimistic-concurrency token, as cache has", () => {
    expect(tableBody("slate_security_policies")).toMatch(
      /policy_version\s+BIGINT NOT NULL DEFAULT 0/,
    );
  });

  it("gives a lane exactly one security policy", () => {
    expect(tableBody("slate_security_policies")).toMatch(/environment_id\s+UUID NOT NULL UNIQUE/);
  });

  it("enumerates the managed tier and the safe bot and rate presets", () => {
    const body = tableBody("slate_security_policies");
    expect(body).toContain("CHECK (managed_ruleset IN ('off', 'core', 'strict'))");
    expect(body).toContain("CHECK (bot_preset IN ('off', 'monitor', 'balanced', 'aggressive'))");
    expect(body).toContain("CHECK (rate_preset IN ('off', 'generous', 'standard', 'strict'))");
  });

  it("keeps preset overrides apart from the preset names", () => {
    expect(tableBody("slate_security_policies")).toMatch(/preset_overrides\s+JSONB NOT NULL/);
  });

  /* ---------------------------------------------------------------------- */
  /* Revisions outlive their rule                                           */
  /* ---------------------------------------------------------------------- */

  it("stores the full prior body of every rule change, so a revert applies a document", () => {
    const body = tableBody("slate_security_rule_revisions");
    expect(body).toMatch(/body\s+JSONB NOT NULL/);
    expect(body).toContain("UNIQUE (rule_id, revision)");
  });

  it("deliberately does not make rule_id a foreign key", () => {
    // A deleted rule is exactly when a revert is most needed, so the history has to outlive the
    // row it describes. A FK with CASCADE would delete the evidence at the moment it is wanted,
    // and a FK with RESTRICT would make the rule undeletable.
    // Read the rule_id column definition and assert on what it says, rather than asserting the
    // absence of a hand-written literal that a reformat could invalidate.
    const body = tableBody("slate_security_rule_revisions");
    const ruleId = /\n\s*rule_id\s+[^\n]*/.exec(body);
    expect(ruleId).not.toBeNull();
    expect(ruleId![0]).toContain("UUID NOT NULL");
    expect(ruleId![0]).not.toContain("REFERENCES");
    // And no other column smuggles the same dependency back in.
    expect(body).not.toContain("REFERENCES apiome.slate_security_rules");
  });

  it("records what produced each revision, so a revert of a revert reads correctly", () => {
    expect(tableBody("slate_security_rule_revisions")).toContain(
      "CHECK (change_kind IN ('created', 'updated', 'disabled', 'deleted',",
    );
    expect(sql).toContain("'reverted', 'rollout-changed')");
  });

  /* ---------------------------------------------------------------------- */
  /* Weakening protection always carries a reason                           */
  /* ---------------------------------------------------------------------- */

  it("refuses to disable the managed ruleset without a stated reason", () => {
    expect(sql).toContain("slate_security_policies_off_needs_reason");
    expect(sql).toContain("CHECK (managed_ruleset <> 'off' OR managed_off_reason IS NOT NULL)");
  });

  it("refuses to turn a managed group off or down to log without a reason", () => {
    expect(sql).toContain("slate_security_managed_groups_weakening_needs_reason");
    expect(sql).toContain("CHECK (mode NOT IN ('off', 'log') OR reason IS NOT NULL)");
  });

  it("gives a managed group one mode per environment", () => {
    const body = tableBody("slate_security_managed_groups");
    expect(body).toContain("UNIQUE (environment_id, group_id)");
    expect(body).toContain("CHECK (mode IN ('off', 'log', 'challenge', 'block'))");
  });

  it("keeps the managed group catalog in code rather than as drifting seed data", () => {
    expect(tableBody("slate_security_managed_groups")).toMatch(/group_id\s+TEXT NOT NULL,/);
    expect(tableBody("slate_security_managed_groups")).not.toContain("group_id       TEXT NOT NULL REFERENCES");
  });

  /* ---------------------------------------------------------------------- */
  /* Digests are format-constrained                                         */
  /* ---------------------------------------------------------------------- */

  it("constrains every digest column to the sha256 form rather than any string", () => {
    const digests: Array<[string, string]> = [
      ["slate_security_rules", "body_digest"],
      ["slate_security_rule_revisions", "body_digest"],
      ["slate_security_approvals", "digest"],
    ];
    for (const [table, column] of digests) {
      expect(tableBody(table)).toMatch(
        new RegExp(`${column}[^,]*\\^sha256:\\[0-9a-f\\]\\{64\\}\\$`),
      );
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Audit is append-only                                                   */
  /* ---------------------------------------------------------------------- */

  it("refuses UPDATE and DELETE on the security audit at the database", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_security_audit_append_only()");
    expect(sql).toContain("BEFORE UPDATE OR DELETE ON apiome.slate_security_audit");
    expect(sql).toContain("is append-only: % is not permitted");
  });

  it("scopes audit entries to what they are about, including who exported the evidence", () => {
    const body = tableBody("slate_security_audit");
    expect(body).toContain(
      "CHECK (subject_kind IN ('policy', 'managed-group', 'rule', 'exception',",
    );
    // Reading the evidence is itself audit-worthy: an export is a disclosure, not a page view.
    expect(body).toContain("'export'");
  });

  it("records whether a person or a system acted", () => {
    expect(tableBody("slate_security_audit")).toContain(
      "CHECK (actor_kind IN ('user', 'automation'))",
    );
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
