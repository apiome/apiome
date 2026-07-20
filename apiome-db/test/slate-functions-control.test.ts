/**
 * Structural assertions over the Slate functions control migration (UXE-3.3, private-suite#2475).
 *
 * V189 adds the edge functions and safe personalization control plane: per-environment policy with
 * residency and resource ceilings, route-matched functions with a staged rollout, immutable
 * content-addressed versions, secret REFERENCES, deny-by-default capabilities and egress,
 * personalization variants that state their cache and privacy effects, revision history,
 * dual-control approvals, redacted invocation evidence and an append-only audit.
 *
 * The suite is DB-free — this package asserts migration SQL structurally, and application against
 * a live database is proven in apiome-rest — so these tests pin the migration's contract. They are
 * weighted toward the claims the schema is what makes true:
 *
 *   1. a secret VALUE has nowhere to live, so exposure is a schema impossibility, not a rule;
 *   2. capabilities and egress are grants-by-row, so a write bug fails closed rather than open;
 *   3. nothing may be recorded as observed or executed on a lane with no runtime;
 *   4. a personalizing variant cannot stay silent about its cache key or its consent basis;
 *   5. the author cannot approve their own change, and one approver cannot approve twice;
 *   6. revision history outlives the function it describes, so a delete is still revertible.
 *
 * The third is the honesty rule. An unenforced cache rule wastes a purge and an unenforced WAF rule
 * leaves an attacker unblocked; a fabricated function EXECUTION is worse than either, because a row
 * saying untrusted code ran and stayed inside its sandbox would be evidence of an isolation
 * guarantee that was never tested. A guarantee that lives only in the service layer survives
 * exactly as long as the next caller behaves, so it is asserted here as a CHECK constraint rather
 * than as documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V189__slate_functions_control_2475.sql";

/** Every table the functions control plane introduces. */
const TABLES = [
  "slate_function_policies",
  "slate_functions",
  "slate_function_versions",
  "slate_function_secret_refs",
  "slate_function_capabilities",
  "slate_function_egress_rules",
  "slate_personalization_variants",
  "slate_function_revisions",
  "slate_function_approvals",
  "slate_function_invocations",
  "slate_function_audit",
] as const;

/**
 * Tables that carry a denormalized tenant_id, per the repo's tenancy convention. Every table here
 * is one — including `slate_function_revisions`, which cannot reach a tenant through its function
 * because that function may already be gone.
 */
const TENANT_SCOPED = TABLES;

/** Keys that must never be storable as invocation evidence, whatever the allowlist grows to. */
const FORBIDDEN_EVIDENCE_KEYS = [
  "cookie",
  "authorization",
  "body",
  "headers",
  "secret",
  "token",
] as const;

/**
 * Name fragments that would betray a column able to hold secret MATERIAL rather than a reference
 * to it. Asserted against `slate_function_secret_refs` in both directions: no column may be named
 * like a value, and no column may be typed like one either.
 */
const SECRET_VALUE_NAME_FRAGMENTS = [
  "value",
  "ciphertext",
  "cipher",
  "plaintext",
  "material",
  "payload",
  "blob",
  "encrypted",
  "token",
  "credential",
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

/**
 * The full declaration line of a named column, so an assertion can inspect its type and its
 * references rather than the whole table.
 *
 * @param table - Table to read from.
 * @param column - Column name.
 * @returns The declaration text, collapsed to one line.
 */
function columnDeclaration(table: string, column: string): string {
  const body = tableBody(table);
  const match = new RegExp(`\\n\\s*${column}\\s+[^\\n]*`).exec(body);
  if (!match) throw new Error(`column ${table}.${column} not found`);
  return match[0].trim();
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

describe("Slate functions control migration", () => {
  /* ---------------------------------------------------------------------- */
  /* Housekeeping                                                           */
  /* ---------------------------------------------------------------------- */

  it("is present in scripts/ and ordered after V188", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V188__slate_security_control_2474.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates every functions control-plane table idempotently", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
    }
  });

  it("names the ticket so the schema is traceable to its rationale", () => {
    expect(sql).toContain("UXE-3.3");
    expect(sql).toContain("private-suite#2475");
    expect(sql).toContain("§29.5");
    expect(sql).toContain("§29.7");
  });

  /* ---------------------------------------------------------------------- */
  /* Tenancy                                                                */
  /* ---------------------------------------------------------------------- */

  it("scopes every functions table to a tenant and cascades deletion", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
      );
    }
  });

  it("keeps tenant_id on function revisions, which cannot reach a tenant through a deleted function", () => {
    expect(tableBody("slate_function_revisions")).toMatch(
      /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Secrets are references, never values                                   */
  /* ---------------------------------------------------------------------- */

  it("gives a secret reference a name, an alias and a scope, and nothing to hold a value in", () => {
    const columns = columnNames("slate_function_secret_refs");
    expect(columns).toContain("secret_name");
    expect(columns).toContain("alias");
    expect(columns).toContain("scope");
    // The claim is structural: there is no column a secret could be written into, correct or not.
    // Enumerating the real column list and rejecting value-shaped names keeps this an assertion
    // about the schema rather than about one hand-written literal that a rename would sidestep.
    for (const column of columns) {
      for (const fragment of SECRET_VALUE_NAME_FRAGMENTS) {
        expect(column.toLowerCase()).not.toContain(fragment);
      }
    }
  });

  it("types every secret-reference column as an identifier rather than a container", () => {
    // A JSONB or bytea column would reintroduce the hiding place the missing value column removes:
    // an opaque blob is exactly where material ends up when nobody is looking.
    const body = tableBody("slate_function_secret_refs");
    expect(body).not.toMatch(/\bJSONB\b/);
    expect(body).not.toMatch(/\bBYTEA\b/i);
    expect(body).not.toMatch(/\bTEXT\[\]/);
    expect(columnDeclaration("slate_function_secret_refs", "secret_name")).toContain("TEXT NOT NULL");
    expect(columnDeclaration("slate_function_secret_refs", "alias")).toContain("TEXT NOT NULL");
  });

  it("says in the table comment that no column here can hold a secret", () => {
    // The comment is the part a future migration author reads before adding a column, so the
    // reasoning has to live in the database and not only in a review thread.
    expect(sql).toContain("COMMENT ON TABLE apiome.slate_function_secret_refs IS");
    const comment = /COMMENT ON TABLE apiome\.slate_function_secret_refs IS\s+'([^']*(?:''[^']*)*)'/
      .exec(sql);
    expect(comment).not.toBeNull();
    expect(comment![1]).toContain("NO column capable of holding a secret value");
  });

  it("scopes a secret reference narrowly by default, so it cannot cross a project boundary", () => {
    const body = tableBody("slate_function_secret_refs");
    expect(body).toMatch(/scope\s+TEXT NOT NULL DEFAULT 'function'/);
    expect(body).toContain("CHECK (scope IN ('function', 'environment'))");
  });

  /* ---------------------------------------------------------------------- */
  /* Deny-by-default is the absence of a row                                */
  /* ---------------------------------------------------------------------- */

  it("models a capability grant as a row rather than as a boolean that can be written wrong", () => {
    const body = tableBody("slate_function_capabilities");
    // No `granted BOOLEAN` anywhere: a bug that fails to write cannot accidentally grant, it can
    // only fail closed. Read the column list rather than asserting a literal's absence.
    for (const column of columnNames("slate_function_capabilities")) {
      expect(column).not.toMatch(/^(granted|allowed|enabled|permitted)$/);
    }
    expect(body).toContain("CHECK (capability IN (");
    expect(body).toContain("UNIQUE (function_id, capability)");
  });

  it("requires a stated reason for every capability grant", () => {
    expect(tableBody("slate_function_capabilities")).toMatch(/reason\s+TEXT NOT NULL/);
  });

  it("records who widened a function's privileges, on an identity that survives offboarding", () => {
    const body = tableBody("slate_function_capabilities");
    expect(body).toMatch(/granted_by_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/);
    expect(body).toMatch(/granted_by_actor_name\s+TEXT NOT NULL/);
    expect(body).toMatch(/granted_by_actor_key\s+TEXT NOT NULL/);
  });

  it("models an egress allowance as a row too, with no wildcard destination kind", () => {
    const body = tableBody("slate_function_egress_rules");
    for (const column of columnNames("slate_function_egress_rules")) {
      expect(column).not.toMatch(/^(granted|allowed|enabled|permitted)$/);
    }
    // An egress allowlist that can say "anything" is a denylist wearing a costume, so the
    // enumeration itself is the guarantee: read it out and assert what it admits.
    const kinds = /CHECK \(destination_kind IN \(([^)]*)\)\)/.exec(body);
    expect(kinds).not.toBeNull();
    expect(kinds![1]).toContain("'exact-host'");
    expect(kinds![1]).toContain("'host-suffix'");
    expect(kinds![1]).not.toMatch(/'(any|all|\*|wildcard)'/);
  });

  it("requires a stated reason for every egress allowance", () => {
    expect(tableBody("slate_function_egress_rules")).toMatch(/reason\s+TEXT NOT NULL/);
  });

  it("lets both grant kinds expire, and refuses an expiry that precedes the grant", () => {
    for (const table of ["slate_function_capabilities", "slate_function_egress_rules"]) {
      const body = tableBody(table);
      const expiry = constraintExpression(body, `${table}_expiry_after_grant`);
      expect(expiry).toContain("expires_at");
      expect(expiry).toContain("granted_at");
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Redaction by allowlist, not denylist                                   */
  /* ---------------------------------------------------------------------- */

  it("constrains invocation evidence to an allowlist by subset, not by a denylist", () => {
    // `jsonb - text[]` removes every listed key, so the result is empty only when every key
    // present was one of the permitted ones. A denylist fails open on the field nobody thought of.
    expect(sql).toContain("slate_function_invocations_evidence_allowlisted");
    expect(sql).toMatch(/CHECK \(evidence - ARRAY\[/);
    expect(sql).toMatch(/= '\{\}'::jsonb\)/);
  });

  it("admits no secret-bearing key into the allowlist", () => {
    const allowlist = /CHECK \(evidence - ARRAY\[([\s\S]*?)\]\s*=\s*'\{\}'::jsonb\)/.exec(sql);
    expect(allowlist).not.toBeNull();
    const keys = allowlist![1].toLowerCase();
    for (const forbidden of FORBIDDEN_EVIDENCE_KEYS) {
      expect(keys).not.toContain(`'${forbidden}'`);
    }
  });

  it("permits the redacted keys an investigation actually needs", () => {
    const body = tableBody("slate_function_invocations");
    for (const key of [
      "method",
      "path",
      "query",
      "userAgent",
      "country",
      "region",
      "clientIpPrefix",
      "variant",
      "outcome",
      "statusCode",
      "denialReason",
    ]) {
      expect(body).toContain(`'${key}'`);
    }
  });

  it("expires captured request data, because evidence is a liability rather than an asset", () => {
    expect(tableBody("slate_function_invocations")).toMatch(
      /retain_until\s+TIMESTAMP WITH TIME ZONE NOT NULL/,
    );
    expect(sql).toContain("slate_function_invocations_retention_after_invocation");
    expect(sql).toContain("CHECK (retain_until > at)");
  });

  /* ---------------------------------------------------------------------- */
  /* Honesty — nothing may claim an observation or an execution that did    */
  /* not happen                                                             */
  /* ---------------------------------------------------------------------- */

  it("forbids claiming code executed on a lane with no runtime", () => {
    expect(sql).toContain("slate_function_invocations_executed_needs_edge");
    expect(sql).toContain("CHECK (executed = FALSE OR edge_attached)");
  });

  it("forbids recording an edge-observed invocation with no edge", () => {
    expect(sql).toContain("slate_function_invocations_observed_needs_edge");
    expect(sql).toContain("CHECK (source <> 'edge-observed' OR edge_attached)");
  });

  it("names edge_attached in both honesty checks rather than inferring it from a join", () => {
    const body = tableBody("slate_function_invocations");
    for (const name of [
      "slate_function_invocations_observed_needs_edge",
      "slate_function_invocations_executed_needs_edge",
    ]) {
      expect(constraintExpression(body, name)).toContain("edge_attached");
    }
  });

  it("defaults an invocation to a simulation that observed and executed nothing", () => {
    const body = tableBody("slate_function_invocations");
    expect(body).toMatch(/source\s+TEXT NOT NULL DEFAULT 'policy-simulation'/);
    expect(body).toMatch(/executed\s+BOOLEAN NOT NULL DEFAULT FALSE/);
    expect(body).toMatch(/edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/);
  });

  it("snapshots edge_attached onto the invocation rather than joining it live", () => {
    // Denormalized deliberately: attaching a runtime later must not make old rows, written when
    // nothing could execute anything, retroactively look executed.
    expect(tableBody("slate_function_policies")).toMatch(
      /edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
    expect(tableBody("slate_function_invocations")).toContain("edge_attached");
  });

  it("states the scope boundary in prose, as V186, V187 and V188 did", () => {
    expect(sql).toContain("Scope boundary, stated plainly");
    expect(sql).toContain("no WASM runtime, no egress proxy and no CDN behind it");
  });

  /* ---------------------------------------------------------------------- */
  /* Personalization states its cache and privacy effects                   */
  /* ---------------------------------------------------------------------- */

  it("keeps audience, fallback, cache-key effect, analytics and privacy in one row", () => {
    const columns = columnNames("slate_personalization_variants");
    for (const column of [
      "audience_kind",
      "audience_matcher",
      "fallback_variant",
      "cache_key_effect",
      "analytics_dimension",
      "privacy_class",
      "consent_basis",
    ]) {
      expect(columns).toContain(column);
    }
  });

  it("requires a fallback, because a variant matching nobody is an outage for the majority", () => {
    expect(tableBody("slate_personalization_variants")).toMatch(
      /fallback_variant\s+TEXT NOT NULL/,
    );
  });

  it("enumerates the cache-key effect, privacy class and consent basis", () => {
    const body = tableBody("slate_personalization_variants");
    expect(body).toContain(
      "CHECK (cache_key_effect IN ('none', 'vary-on-dimension', 'bypass-cache'))",
    );
    expect(body).toContain(
      "CHECK (privacy_class IN ('non-personal', 'pseudonymous', 'personal'))",
    );
    expect(body).toContain("consent_basis IN ('not-required', 'explicit-consent',");
  });

  it("refuses a personal variant that claims consent was not required", () => {
    const body = tableBody("slate_personalization_variants");
    const check = constraintExpression(
      body,
      "slate_personalization_variants_personal_needs_basis",
    );
    expect(check).toContain("privacy_class");
    expect(check).toContain("consent_basis");
  });

  it("refuses a personalizing variant that stays silent about the cache key", () => {
    // A shared cache entry that differs per reader is the defect §29.3 already refuses for cache;
    // it is the same defect when a function causes it.
    const check = constraintExpression(
      tableBody("slate_personalization_variants"),
      "slate_personalization_variants_personal_needs_cache_effect",
    );
    expect(check).toContain("cache_key_effect");
    expect(check).toContain("privacy_class");
  });

  /* ---------------------------------------------------------------------- */
  /* Deterministic evaluation, staged rollout and declared limits           */
  /* ---------------------------------------------------------------------- */

  it("makes function precedence a total order rather than a set with ties", () => {
    expect(tableBody("slate_functions")).toContain("UNIQUE (environment_id, ordinal)");
  });

  it("defaults a function to simulate at zero percent, so execution is a deliberate sequence", () => {
    const body = tableBody("slate_functions");
    expect(body).toMatch(/rollout_mode\s+TEXT NOT NULL DEFAULT 'simulate'/);
    expect(body).toContain("CHECK (rollout_mode IN ('simulate', 'enforce'))");
    expect(body).toMatch(/rollout_percent\s+INTEGER NOT NULL DEFAULT 0/);
    expect(body).toContain("CHECK (rollout_percent BETWEEN 0 AND 100)");
  });

  it("uses the same four matcher kinds as the cache and security rules", () => {
    expect(tableBody("slate_functions")).toContain(
      "CHECK (matcher_kind IN ('exact', 'prefix', 'glob', 'regex'))",
    );
  });

  it("gives a lane exactly one function policy, with an optimistic-concurrency token", () => {
    const body = tableBody("slate_function_policies");
    expect(body).toMatch(/environment_id\s+UUID NOT NULL UNIQUE/);
    expect(body).toMatch(/policy_version\s+BIGINT NOT NULL DEFAULT 0/);
  });

  it("declares a default region, residency class and resource ceilings on the lane", () => {
    const body = tableBody("slate_function_policies");
    expect(body).toMatch(/default_region\s+TEXT NOT NULL/);
    expect(body).toContain(
      "CHECK (default_residency_class IN ('in-region-only', 'region-pinned',",
    );
    expect(body).toMatch(/default_cpu_ms_limit\s+INTEGER NOT NULL DEFAULT \d+/);
    expect(body).toMatch(/default_memory_mb_limit\s+INTEGER NOT NULL DEFAULT \d+/);
    expect(body).toMatch(/default_wall_ms_limit\s+INTEGER NOT NULL DEFAULT \d+/);
  });

  it("names an edge provider column so attaching a runtime is a data change", () => {
    const body = tableBody("slate_function_policies");
    expect(body).toMatch(/edge_provider\s+TEXT/);
  });

  it("refuses to enforce a function with no version to enforce", () => {
    const check = constraintExpression(
      tableBody("slate_functions"),
      "slate_functions_enforce_needs_version",
    );
    expect(check).toContain("rollout_mode");
    expect(check).toContain("active_version_id");
  });

  /* ---------------------------------------------------------------------- */
  /* Immutable, content-addressed versions                                  */
  /* ---------------------------------------------------------------------- */

  it("content-addresses every function version and keeps one per revision", () => {
    const body = tableBody("slate_function_versions");
    expect(body).toMatch(/source_digest\s+TEXT NOT NULL CHECK/);
    expect(body).toMatch(/body\s+JSONB NOT NULL/);
    expect(body).toContain("UNIQUE (function_id, revision)");
    expect(body).toContain("CHECK (revision >= 1)");
  });

  it("keeps a version bound to a live function, unlike a revision", () => {
    // The two tables take opposite decisions on purpose: a version is for promoting, so it should
    // vanish with its function; a revision is for remembering, so it must not.
    expect(columnDeclaration("slate_function_versions", "function_id")).toContain("UUID NOT NULL");
    expect(tableBody("slate_function_versions")).toContain(
      "REFERENCES apiome.slate_functions(id) ON DELETE CASCADE",
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Revisions outlive their function                                       */
  /* ---------------------------------------------------------------------- */

  it("stores the full prior body of every function change, so a revert applies a document", () => {
    const body = tableBody("slate_function_revisions");
    expect(body).toMatch(/body\s+JSONB NOT NULL/);
    expect(body).toContain("UNIQUE (function_id, revision)");
  });

  it("deliberately does not make revisions.function_id a foreign key", () => {
    // A deleted function is exactly when a revert is most needed, so the history has to outlive the
    // row it describes. A FK with CASCADE would delete the evidence at the moment it is wanted, and
    // a FK with RESTRICT would make the function undeletable. Read the column declaration and
    // assert on what it says, rather than asserting the absence of a hand-written literal.
    const declaration = columnDeclaration("slate_function_revisions", "function_id");
    expect(declaration).toContain("UUID NOT NULL");
    expect(declaration).not.toContain("REFERENCES");
    // And no other column smuggles the same dependency back in.
    expect(tableBody("slate_function_revisions")).not.toContain(
      "REFERENCES apiome.slate_functions",
    );
  });

  it("records what produced each revision, including a version promotion", () => {
    const body = tableBody("slate_function_revisions");
    expect(body).toContain("CHECK (change_kind IN ('created', 'updated', 'disabled', 'deleted',");
    expect(body).toContain("'reverted', 'rollout-changed', 'version-added')");
  });

  /* ---------------------------------------------------------------------- */
  /* Dual control                                                           */
  /* ---------------------------------------------------------------------- */

  it("forbids an author approving their own change", () => {
    expect(sql).toContain("slate_function_approvals_distinct_actors");
    expect(sql).toContain("CHECK (approver_actor_key <> author_actor_key)");
  });

  it("compares the immutable identity keys, not the nullable user ids", () => {
    // The whole point of the *_key columns. The *_actor_id columns are ON DELETE SET NULL, so a
    // distinctness CHECK over them would turn a genuine two-person approval into two NULLs that no
    // longer look distinct — a constraint that weakens when somebody is offboarded.
    const body = tableBody("slate_function_approvals");
    expect(body).toMatch(/author_actor_key\s+TEXT NOT NULL/);
    expect(body).toMatch(/approver_actor_key\s+TEXT NOT NULL/);
    expect(body).toMatch(/author_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/);
    expect(body).toMatch(
      /approver_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/,
    );
    // Asserted semantically rather than by absence of one exact literal: pull the distinctness
    // CHECK out of the table body and inspect what it actually names.
    const distinctness = constraintExpression(body, "slate_function_approvals_distinct_actors");
    expect(distinctness).toContain("approver_actor_key");
    expect(distinctness).toContain("author_actor_key");
    expect(distinctness).not.toMatch(/_actor_id\b/);
  });

  it("lets one approver approve a given body once, so two clicks are not two approvals", () => {
    const body = tableBody("slate_function_approvals");
    expect(body).toContain("UNIQUE (subject_id, digest, approver_actor_key)");
    // Keyed on the identity string for the same reason: two NULL user ids would be distinct rows
    // under a UNIQUE that named approver_actor_id, so the duplicate would sail through.
    const unique = uniqueClause(body);
    expect(unique).toContain("approver_actor_key");
    expect(unique).not.toMatch(/_actor_id\b/);
  });

  it("content-addresses what was approved, so a stale approval is detectable", () => {
    expect(tableBody("slate_function_approvals")).toMatch(
      /digest\s+TEXT NOT NULL CHECK \(digest ~ '\^sha256:\[0-9a-f\]\{64\}\$'\)/,
    );
  });

  it("covers every subject a function change can have", () => {
    const body = tableBody("slate_function_approvals");
    for (const kind of ["'policy'", "'function'", "'version'", "'capability'", "'egress-rule'", "'variant'"]) {
      expect(body).toContain(kind);
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Digests are format-constrained                                         */
  /* ---------------------------------------------------------------------- */

  it("constrains every digest column to the sha256 form rather than any string", () => {
    const digests: Array<[string, string]> = [
      ["slate_functions", "body_digest"],
      ["slate_function_versions", "source_digest"],
      ["slate_function_revisions", "body_digest"],
      ["slate_function_approvals", "digest"],
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

  it("refuses UPDATE and DELETE on the functions audit at the database", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_function_audit_append_only()");
    expect(sql).toContain("BEFORE UPDATE OR DELETE ON apiome.slate_function_audit");
    expect(sql).toContain("trg_slate_function_audit_append_only");
    expect(sql).toContain("is append-only: % is not permitted");
    expect(sql).toContain("USING ERRCODE = '23514'");
  });

  it("scopes audit entries to what they are about, including who exported the evidence", () => {
    const body = tableBody("slate_function_audit");
    expect(body).toContain("CHECK (subject_kind IN ('policy', 'function', 'version', 'secret-ref',");
    // Reading the evidence is itself audit-worthy: an export is a disclosure, not a page view.
    expect(body).toContain("'export'");
  });

  it("records whether a person or a system acted", () => {
    expect(tableBody("slate_function_audit")).toContain(
      "CHECK (actor_kind IN ('user', 'automation'))",
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Enumerations are CHECKs, not Postgres ENUM types                       */
  /* ---------------------------------------------------------------------- */

  it("uses inline CHECK enumerations rather than Postgres ENUM types", () => {
    // A CREATE TYPE ... AS ENUM cannot have a value removed and needs a migration to add one, so
    // the repo's convention is an inline CHECK. Asserted here so the convention survives review.
    expect(lower).not.toContain("create type");
    expect(lower).not.toContain("as enum");
  });

  it("grants nothing, leaving privileges to the roles the deployment already defines", () => {
    // Matched as a statement rather than as the word: the rationale prose talks about grants
    // constantly, and a bare substring check would fail on its own explanation.
    expect(sql).not.toMatch(/\bGRANT\s+(SELECT|INSERT|UPDATE|DELETE|ALL|USAGE|EXECUTE)\b/i);
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

  it("indexes every table on its tenant, so a tenant-scoped read is never a sequential scan", () => {
    for (const table of TABLES) {
      expect(sql).toMatch(new RegExp(`ON apiome\\.${table} \\(tenant_id[,)]`));
    }
  });
});
