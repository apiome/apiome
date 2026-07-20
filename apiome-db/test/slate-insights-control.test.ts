/**
 * Structural assertions over the Slate insights control migration (UXE-3.4, private-suite#2476).
 *
 * V190 adds the unified observability, residency, usage and budget control plane: per-environment
 * insight policy with retention windows and sampling ceilings, stage-by-stage residency lanes that
 * state what they do NOT cover, release-correlated metric series, structured logs and trace
 * waterfalls with allowlisted evidence, sampled and rate-limited live tail, OpenTelemetry export
 * destinations that hold a secret REFERENCE rather than a header, synthetic regional health with
 * post-promotion annotations, daily metered-or-modelled usage and spend, budgets with alerts, and
 * an append-only audit.
 *
 * The suite is DB-free — this package asserts migration SQL structurally, and application against
 * a live database is proven in apiome-rest — so these tests pin the migration's contract. They are
 * weighted toward the claims the schema is what makes true:
 *
 *   1. no signal may call itself observed on a lane nothing observes;
 *   2. no row may be billed, credited or delivered on the strength of a model;
 *   3. a header VALUE has nowhere to live, so exposure is a schema impossibility, not a rule;
 *   4. a residency lane cannot claim to cover everything by saying nothing;
 *   5. request data expires, while the audit that records who read it does not;
 *   6. evidence is redacted by allowlist, so an unlisted key cannot be stored at all.
 *
 * The first two are the honesty rules, and they are why this migration is stricter than its three
 * predecessors. A cache rule that does not fire wastes a purge and a WAF rule that does not fire
 * leaves an attacker unblocked; those are inert. A latency chart that is quietly modelled is acted
 * upon — somebody reads a p95 and promotes a release — and a modelled cost presented as a bill is
 * not a disappointing estimate but an invented invoice. A guarantee that lives only in the service
 * layer survives exactly as long as the next caller behaves, so each of these is asserted here as a
 * named CHECK constraint rather than as documentation.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V190__slate_insights_control_2476.sql";

/** Every table the insights control plane introduces. */
const TABLES = [
  "slate_insight_policies",
  "slate_residency_lanes",
  "slate_insight_metric_series",
  "slate_insight_logs",
  "slate_insight_traces",
  "slate_insight_trace_spans",
  "slate_insight_live_tail_sessions",
  "slate_insight_otlp_exports",
  "slate_insight_synthetic_checks",
  "slate_insight_synthetic_results",
  "slate_insight_usage_records",
  "slate_insight_budgets",
  "slate_insight_budget_alerts",
  "slate_insight_audit",
] as const;

/** Tables that carry a denormalized tenant_id, per the repo's tenancy convention. Every table here. */
const TENANT_SCOPED = TABLES;

/**
 * The signal tables §29.6 requires to correlate. Each must carry the same three columns with the
 * same names and types, so correlating them is a schema fact rather than a query convention.
 */
const SIGNAL_TABLES = [
  "slate_insight_metric_series",
  "slate_insight_logs",
  "slate_insight_traces",
  "slate_insight_synthetic_results",
  "slate_insight_usage_records",
] as const;

/** The four tables that capture request data, and therefore must expire it. */
const RETAINED_TABLES: Array<{ table: string; constraint: string; after: string }> = [
  {
    table: "slate_insight_logs",
    constraint: "slate_insight_logs_retention_after_event",
    after: "at",
  },
  {
    table: "slate_insight_traces",
    constraint: "slate_insight_traces_retention_after_start",
    after: "started_at",
  },
  {
    table: "slate_insight_live_tail_sessions",
    constraint: "slate_insight_live_tail_sessions_retention_after_start",
    after: "started_at",
  },
  {
    table: "slate_insight_synthetic_results",
    constraint: "slate_insight_synthetic_results_retention_after_run",
    after: "at",
  },
];

/** The four tables whose `basis` may read edge-observed only with an edge attached. */
const OBSERVED_NEEDS_EDGE = [
  "slate_insight_metric_series",
  "slate_insight_logs",
  "slate_insight_traces",
  "slate_insight_synthetic_results",
] as const;

/** Keys that must never be storable as evidence or attributes, whatever the allowlists grow to. */
const FORBIDDEN_EVIDENCE_KEYS = [
  "cookie",
  "authorization",
  "header",
  "credential",
  "body",
  "secret",
  "token",
  "password",
] as const;

/**
 * Name fragments that would betray a column able to hold header MATERIAL rather than a reference to
 * it. Asserted against `slate_insight_otlp_exports` in both directions, exactly as V189 asserted
 * them against `slate_function_secret_refs`: no column may be named like a value, and no column may
 * be typed like a container either.
 */
const HEADER_VALUE_NAME_FRAGMENTS = [
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
  "bearer",
  "authorization",
] as const;

/** The six processing stages §29.6 distinguishes, in request-path order. */
const RESIDENCY_STAGES = [
  "ingress",
  "tls-termination",
  "decrypted-processing",
  "cache-storage",
  "function-execution",
  "log-data-storage",
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
    const match =
      /^([a-z_]+)\s+(UUID|TEXT|INTEGER|BIGINT|BOOLEAN|JSONB|TIMESTAMP|NUMERIC|DATE)/.exec(trimmed);
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
 * Several claims in this suite are negative — "the OTLP table names no column able to hold a header
 * value". Asserting those by `not.toContain("<some exact literal>")` is fragile in the worst way:
 * it passes whether the migration is correct or merely formatted differently, so a reformat would
 * leave the test green while it proved nothing. Reading the real expression out and inspecting what
 * it names keeps the assertion semantic.
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

/**
 * The key list of an `X - ARRAY[...] = '{}'::jsonb` allowlist CHECK, lowercased.
 *
 * @param table - Table declaring the allowlist.
 * @param column - The JSONB column the allowlist constrains.
 * @returns The allowlisted keys as one lowercased string.
 */
function allowlistKeys(table: string, column: string): string {
  const body = tableBody(table);
  const match = new RegExp(`${column} - ARRAY\\[([\\s\\S]*?)\\]\\s*=\\s*'\\{\\}'::jsonb`).exec(body);
  if (!match) throw new Error(`no allowlist CHECK for ${table}.${column}`);
  return match[1].toLowerCase();
}

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("Slate insights control migration", () => {
  /* ---------------------------------------------------------------------- */
  /* Housekeeping                                                           */
  /* ---------------------------------------------------------------------- */

  it("is present in scripts/ and ordered after V189", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V189__slate_functions_control_2475.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("creates every insights control-plane table idempotently", () => {
    for (const table of TABLES) {
      expect(sql).toContain(`CREATE TABLE IF NOT EXISTS apiome.${table} (`);
    }
  });

  it("names the ticket so the schema is traceable to its rationale", () => {
    expect(sql).toContain("UXE-3.4");
    expect(sql).toContain("private-suite#2476");
    expect(sql).toContain("§29.6");
    expect(sql).toContain("§28.4");
    expect(sql).toContain("§29.7");
  });

  /* ---------------------------------------------------------------------- */
  /* Tenancy                                                                */
  /* ---------------------------------------------------------------------- */

  it("scopes every insights table to a tenant and cascades deletion", () => {
    for (const table of TENANT_SCOPED) {
      expect(tableBody(table)).toMatch(
        /tenant_id\s+UUID NOT NULL REFERENCES apiome\.tenants\(id\) ON DELETE CASCADE/,
      );
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Correlation is a schema fact, not a join convention                    */
  /* ---------------------------------------------------------------------- */

  it("gives every signal table the same three correlation columns, so a chart and its drill-down cannot mean different rows", () => {
    for (const table of SIGNAL_TABLES) {
      const columns = columnNames(table);
      expect(columns).toContain("environment_id");
      expect(columns).toContain("release_id");
      expect(columns).toContain("region");
    }
  });

  it("makes the environment mandatory on every signal, so a signal that cannot be correlated cannot be written", () => {
    for (const table of SIGNAL_TABLES) {
      expect(columnDeclaration(table, "environment_id")).toContain("UUID NOT NULL");
    }
  });

  it("keeps a signal after its release is retired rather than deleting the history with it", () => {
    for (const table of SIGNAL_TABLES) {
      expect(columnDeclaration(table, "release_id")).toContain(
        "REFERENCES apiome.slate_releases(id) ON DELETE SET NULL",
      );
    }
  });

  it("types region identically everywhere, so cost allocation correlates with latency through one column", () => {
    for (const table of SIGNAL_TABLES) {
      expect(columnDeclaration(table, "region")).toMatch(/region\s+TEXT NOT NULL DEFAULT 'auto'/);
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Honesty — nothing may claim an observation, a delivery or a charge     */
  /* that did not happen                                                    */
  /* ---------------------------------------------------------------------- */

  it("forbids recording an edge-observed metric, log, trace or synthetic result with no edge", () => {
    for (const table of OBSERVED_NEEDS_EDGE) {
      const name = `${table}_observed_needs_edge`;
      expect(sql).toContain(name);
      expect(constraintExpression(tableBody(table), name)).toBe(
        "(basis <> 'edge-observed' OR edge_attached)",
      );
    }
  });

  it("defaults every signal to a model that observed nothing, so measurement is a deliberate act", () => {
    for (const table of OBSERVED_NEEDS_EDGE) {
      const body = tableBody(table);
      expect(body).toMatch(/basis\s+TEXT NOT NULL DEFAULT 'modelled'/);
      expect(body).toMatch(/edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/);
      expect(body).toContain("CHECK (basis IN ('modelled', 'edge-observed'))");
    }
  });

  it("forbids claiming a live tail is attached to a lane with nothing in the request path", () => {
    const name = "slate_insight_live_tail_sessions_attached_needs_edge";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_live_tail_sessions"), name)).toBe(
      "(stream_state <> 'attached' OR edge_attached)",
    );
  });

  it("forbids a live tail session that never attached from claiming it delivered anything, which is what makes events_delivered safe to sum", () => {
    const name = "slate_insight_live_tail_sessions_delivery_needs_attach";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_live_tail_sessions"), name)).toBe(
      "(events_delivered = 0 OR edge_attached)",
    );
  });

  it("forbids an OTLP destination from reading delivered while nothing is attached to deliver it", () => {
    const name = "slate_insight_otlp_exports_delivered_needs_edge";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_otlp_exports"), name)).toBe(
      "(last_delivery_state <> 'delivered' OR edge_attached)",
    );
  });

  it("forbids a budget alert from reading delivered while nothing is attached to dispatch it", () => {
    const name = "slate_insight_budget_alerts_delivered_needs_edge";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_budget_alerts"), name)).toBe(
      "(delivery_state <> 'delivered' OR edge_attached)",
    );
  });

  it("forbids billing a modelled usage row, so a projection cannot become an invoice", () => {
    // The single most consequential constraint in the migration. A modelled number may be charted,
    // forecast, compared and exported; it may not be charged for.
    const name = "slate_insight_usage_records_billable_needs_meter";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_usage_records"), name)).toBe(
      "(billable = FALSE OR basis = 'metered')",
    );
  });

  it("forbids a metered usage claim on a lane nothing metered, so the billable gate cannot be walked around", () => {
    // Without this, `basis = 'metered'` would be a free-text promotion and the billable CHECK above
    // would be satisfied by writing one extra word.
    const name = "slate_insight_usage_records_metered_needs_edge";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_usage_records"), name)).toBe(
      "(basis <> 'metered' OR edge_attached)",
    );
  });

  it("forbids crediting cache savings computed from a model, which is a discount nobody gave", () => {
    const name = "slate_insight_usage_records_savings_needs_meter";
    expect(sql).toContain(name);
    expect(constraintExpression(tableBody("slate_insight_usage_records"), name)).toBe(
      "(cache_savings_amount IS NULL OR basis = 'metered')",
    );
  });

  it("defaults a usage record to modelled and unbillable, so charging is opted into rather than inherited", () => {
    const body = tableBody("slate_insight_usage_records");
    expect(body).toMatch(/basis\s+TEXT NOT NULL DEFAULT 'modelled'/);
    expect(body).toContain("CHECK (basis IN ('modelled', 'metered'))");
    expect(body).toMatch(/billable\s+BOOLEAN NOT NULL DEFAULT FALSE/);
    expect(body).toMatch(/edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/);
  });

  it("keeps a forecast in its own column so a projection can never be summed into a total as though it had happened", () => {
    expect(columnDeclaration("slate_insight_usage_records", "forecast_amount")).toMatch(
      /forecast_amount\s+NUMERIC\(20, 6\) CHECK \(forecast_amount IS NULL/,
    );
  });

  it("snapshots edge_attached onto every honesty-constrained row rather than joining it live", () => {
    // Denormalized deliberately: attaching a collector later must not make old rows, written when
    // nothing could observe anything, retroactively look measured.
    expect(tableBody("slate_insight_policies")).toMatch(
      /edge_attached\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
    for (const table of [
      ...OBSERVED_NEEDS_EDGE,
      "slate_insight_live_tail_sessions",
      "slate_insight_otlp_exports",
      "slate_insight_usage_records",
      "slate_insight_budget_alerts",
    ]) {
      expect(columnNames(table)).toContain("edge_attached");
    }
  });

  it("states the scope boundary in prose, as V186, V187, V188 and V189 did", () => {
    expect(sql).toContain("Scope boundary, stated plainly");
    expect(sql).toContain("no isolate pool and no collector behind it");
  });

  /* ---------------------------------------------------------------------- */
  /* An OTLP header value has nowhere to live                               */
  /* ---------------------------------------------------------------------- */

  it("gives an OTLP destination a secret reference and nothing to hold a header value in", () => {
    const columns = columnNames("slate_insight_otlp_exports");
    expect(columns).toContain("header_secret_ref");
    // The claim is structural: there is no column a bearer token could be written into, correct or
    // not. Enumerating the real column list and rejecting value-shaped names keeps this an
    // assertion about the schema rather than about one hand-written literal a rename would sidestep.
    for (const column of columns) {
      for (const fragment of HEADER_VALUE_NAME_FRAGMENTS) {
        expect(column.toLowerCase()).not.toContain(fragment);
      }
    }
  });

  it("types the OTLP destination's columns as identifiers rather than containers", () => {
    // A JSONB or bytea column would reintroduce the hiding place the missing header column removes:
    // an opaque blob is exactly where an authorization header ends up when nobody is looking.
    const body = tableBody("slate_insight_otlp_exports");
    expect(body).not.toMatch(/\bJSONB\b/);
    expect(body).not.toMatch(/\bBYTEA\b/i);
    expect(columnDeclaration("slate_insight_otlp_exports", "header_secret_ref")).toMatch(
      /header_secret_ref\s+TEXT/,
    );
  });

  it("says in the table comment that no column here can hold a header value", () => {
    // The comment is the part a future migration author reads before adding a column, so the
    // reasoning has to live in the database and not only in a review thread.
    const comment = /COMMENT ON TABLE apiome\.slate_insight_otlp_exports IS\s+'([^']*(?:''[^']*)*)'/
      .exec(sql);
    expect(comment).not.toBeNull();
    expect(comment![1]).toContain("no column able to hold a header value");
  });

  it("stores the budget notification target as a reference too, because a webhook URL carries its own credential", () => {
    expect(columnDeclaration("slate_insight_budgets", "notify_channel_ref")).toMatch(
      /notify_channel_ref\s+TEXT/,
    );
    for (const column of columnNames("slate_insight_budgets")) {
      expect(column.toLowerCase()).not.toContain("webhook_url");
    }
  });

  /* ---------------------------------------------------------------------- */
  /* Residency states what it does not cover                                */
  /* ---------------------------------------------------------------------- */

  it("requires every residency lane to state what it does not cover, so a lane cannot claim everything by saying nothing", () => {
    // NOT NULL is the whole point. A residency claim with no stated gap is not a stronger promise
    // than one with a gap; it is the same promise with the gap unwritten, and it is the version
    // somebody quotes to a regulator.
    expect(columnDeclaration("slate_residency_lanes", "uncovered_sentence")).toMatch(
      /uncovered_sentence\s+TEXT NOT NULL/,
    );
  });

  it("closes the residency stage vocabulary over exactly the six stages §29.6 names", () => {
    const body = tableBody("slate_residency_lanes");
    const stages = /CHECK \(stage IN \(([\s\S]*?)\)\)/.exec(body);
    expect(stages).not.toBeNull();
    const listed = stages![1].match(/'([a-z-]+)'/g)?.map((s) => s.slice(1, -1)) ?? [];
    expect(listed).toEqual([...RESIDENCY_STAGES]);
  });

  it("makes stage a closed enum rather than free text, because a freely named stage can be omitted by never being mentioned", () => {
    expect(columnDeclaration("slate_residency_lanes", "stage")).toContain("TEXT NOT NULL");
    expect(tableBody("slate_residency_lanes")).toContain("CHECK (stage IN (");
  });

  it("gives a lane one row per stage, which is what makes 'all six are shown' a query rather than a hope", () => {
    const body = tableBody("slate_residency_lanes");
    expect(body).toContain("UNIQUE (environment_id, stage)");
    expect(uniqueClause(body)).toBe("environment_id, stage");
  });

  it("spells the residency classes exactly as the function policy does, so two surfaces cannot spell one promise differently", () => {
    expect(tableBody("slate_residency_lanes")).toContain(
      "residency_class IN ('in-region-only', 'region-pinned',",
    );
  });

  it("requires a stated reason before a stage is loosened to unrestricted", () => {
    const check = constraintExpression(
      tableBody("slate_residency_lanes"),
      "slate_residency_lanes_unrestricted_needs_reason",
    );
    expect(check).toContain("residency_class");
    expect(check).toContain("residency_waiver_reason");
  });

  it("refuses a confined stage that names no region, which reads as the strictest promise and means nothing", () => {
    const check = constraintExpression(
      tableBody("slate_residency_lanes"),
      "slate_residency_lanes_confined_needs_regions",
    );
    expect(check).toContain("cardinality(regions) > 0");
  });

  /* ---------------------------------------------------------------------- */
  /* Redaction by allowlist, not denylist                                   */
  /* ---------------------------------------------------------------------- */

  it("constrains log evidence and span attributes to an allowlist by subtraction, not by a denylist", () => {
    // `jsonb - text[]` removes every listed key, so the result is empty only when every key present
    // was one of the permitted ones. A denylist fails open on the field nobody thought of.
    for (const [table, column, name] of [
      ["slate_insight_logs", "evidence", "slate_insight_logs_evidence_allowlisted"],
      [
        "slate_insight_trace_spans",
        "attributes",
        "slate_insight_trace_spans_attributes_allowlisted",
      ],
    ] as const) {
      expect(sql).toContain(name);
      const body = tableBody(table);
      expect(body).toContain(`CHECK (${column} - ARRAY[`);
      expect(body).toContain("= '{}'::jsonb)");
    }
  });

  it("admits no cookie, authorization or other credential-bearing key into either allowlist", () => {
    for (const [table, column] of [
      ["slate_insight_logs", "evidence"],
      ["slate_insight_trace_spans", "attributes"],
    ] as const) {
      const keys = allowlistKeys(table, column);
      for (const forbidden of FORBIDDEN_EVIDENCE_KEYS) {
        expect(keys).not.toContain(forbidden);
      }
    }
  });

  it("permits the redacted keys an investigation actually needs", () => {
    const keys = allowlistKeys("slate_insight_logs", "evidence");
    for (const key of [
      "method",
      "path",
      "query",
      "useragent",
      "country",
      "region",
      "clientipprefix",
      "statuscode",
      "durationms",
      "cachestatus",
      "outcome",
    ]) {
      expect(keys).toContain(`'${key}'`);
    }
  });

  it("defaults both allowlisted columns to the empty object, so an unwritten evidence column is empty rather than absent", () => {
    expect(columnDeclaration("slate_insight_logs", "evidence")).toContain(
      "JSONB NOT NULL DEFAULT '{}'::jsonb",
    );
    expect(columnDeclaration("slate_insight_trace_spans", "attributes")).toContain(
      "JSONB NOT NULL DEFAULT '{}'::jsonb",
    );
  });

  it("stores the allowlist a live tail ran under, so a capture reviewed later is checked against its own redaction", () => {
    expect(columnDeclaration("slate_insight_live_tail_sessions", "redaction_allowlist")).toMatch(
      /redaction_allowlist\s+TEXT\[\] NOT NULL/,
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Request data expires; the audit does not                               */
  /* ---------------------------------------------------------------------- */

  it("expires every table that captures request data, because evidence is a liability rather than an asset", () => {
    for (const { table } of RETAINED_TABLES) {
      expect(columnDeclaration(table, "retain_until")).toContain(
        "TIMESTAMP WITH TIME ZONE NOT NULL",
      );
    }
  });

  it("orders every retention deadline after the event it retains, so retain_until cannot be set in the past", () => {
    for (const { table, constraint, after } of RETAINED_TABLES) {
      expect(sql).toContain(constraint);
      expect(constraintExpression(tableBody(table), constraint)).toBe(
        `(retain_until > ${after})`,
      );
    }
  });

  it("indexes every retention deadline, so the sweep that enforces it is not a sequential scan", () => {
    for (const { table } of RETAINED_TABLES) {
      expect(sql).toMatch(new RegExp(`ON apiome\\.${table} \\(retain_until\\)`));
    }
  });

  it("gives the audit no retention at all, because the record of who read the evidence outlives the evidence", () => {
    // Asserted by reading the audit's real column list rather than by the absence of one literal:
    // the audit is the only durable trace of a disclosure, and expiring it would delete the
    // accountability along with the request data it was about.
    const columns = columnNames("slate_insight_audit");
    expect(columns).not.toContain("retain_until");
    for (const column of columns) {
      expect(column).not.toMatch(/retain|expires|purge/);
    }
  });

  it("keeps retention windows per signal class rather than as one shared number", () => {
    const body = tableBody("slate_insight_policies");
    expect(body).toMatch(/metric_retention_days\s+INTEGER NOT NULL DEFAULT \d+/);
    expect(body).toMatch(/log_retention_days\s+INTEGER NOT NULL DEFAULT \d+/);
    expect(body).toMatch(/trace_retention_days\s+INTEGER NOT NULL DEFAULT \d+/);
  });

  it("requires a stated reason before log retention drops below the incident-review floor", () => {
    const check = constraintExpression(
      tableBody("slate_insight_policies"),
      "slate_insight_policies_short_log_retention_needs_reason",
    );
    expect(check).toContain("log_retention_days");
    expect(check).toContain("retention_waiver_reason IS NOT NULL");
  });

  /* ---------------------------------------------------------------------- */
  /* Paired columns cannot half-exist                                       */
  /* ---------------------------------------------------------------------- */

  it("refuses a suppressed metric that still carries the value it suppressed, and a reported one with no value", () => {
    // Asserted from both sides deliberately. A one-sided rule would let a suppressed row keep the
    // number in the column and leave every future reader to remember not to read it.
    const check = constraintExpression(
      tableBody("slate_insight_metric_series"),
      "slate_insight_metric_series_suppressed_has_no_value",
    );
    expect(check).toContain("suppressed AND value IS NULL");
    expect(check).toContain("NOT suppressed AND value IS NOT NULL");
  });

  it("suppresses a low-volume metric rather than perturbing it, so a withheld cell is legible to an auditor", () => {
    const body = tableBody("slate_insight_metric_series");
    expect(body).toMatch(/sample_count\s+BIGINT NOT NULL DEFAULT 0 CHECK \(sample_count >= 0\)/);
    expect(body).toMatch(/suppressed\s+BOOLEAN NOT NULL DEFAULT FALSE/);
    expect(tableBody("slate_insight_policies")).toMatch(
      /privacy_threshold\s+INTEGER NOT NULL DEFAULT \d+ CHECK \(privacy_threshold >= 1\)/,
    );
  });

  it("refuses a synthetic annotation kind without its note, and a note without its kind", () => {
    const check = constraintExpression(
      tableBody("slate_insight_synthetic_results"),
      "slate_insight_synthetic_results_annotation_paired",
    );
    expect(check).toContain("annotation_kind IS NULL AND annotation_note IS NULL");
    expect(check).toContain("annotation_kind IS NOT NULL AND annotation_note IS NOT NULL");
  });

  it("refuses a post-promotion annotation with no release to drill into, which is the only thing an operator wants from it", () => {
    const check = constraintExpression(
      tableBody("slate_insight_synthetic_results"),
      "slate_insight_synthetic_results_annotation_needs_release",
    );
    expect(check).toBe("(annotation_kind IS NULL OR release_id IS NOT NULL)");
  });

  it("enumerates the two post-promotion annotation kinds rather than accepting any label", () => {
    expect(tableBody("slate_insight_synthetic_results")).toContain(
      "annotation_kind IN ('post-promotion-regression',",
    );
  });

  it("refuses an acknowledgement that names a time without a person, or a person without a time", () => {
    const check = constraintExpression(
      tableBody("slate_insight_budget_alerts"),
      "slate_insight_budget_alerts_acknowledgement_complete",
    );
    expect(check).toContain("acknowledged_at IS NULL AND acknowledged_by_actor_key IS NULL");
    expect(check).toContain("acknowledged_at IS NOT NULL");
    expect(check).toContain("acknowledged_by_actor_key IS NOT NULL");
    expect(check).toContain("acknowledged_by_actor_name IS NOT NULL");
  });

  it("refuses an OTLP failure with no reason, which is a state an operator cannot act on", () => {
    const check = constraintExpression(
      tableBody("slate_insight_otlp_exports"),
      "slate_insight_otlp_exports_failure_needs_reason",
    );
    expect(check).toBe("(last_delivery_state <> 'failed' OR last_failure_reason IS NOT NULL)");
  });

  /* ---------------------------------------------------------------------- */
  /* Live tail is sampled, rate-limited and attributable                    */
  /* ---------------------------------------------------------------------- */

  it("makes sampling and rate limiting columns rather than client courtesy, so a session can be audited for exceeding one", () => {
    const body = tableBody("slate_insight_live_tail_sessions");
    expect(body).toMatch(/sample_rate\s+NUMERIC\(6, 5\) NOT NULL/);
    expect(body).toContain("CHECK (sample_rate > 0 AND sample_rate <= 1)");
    expect(body).toMatch(/max_events_per_sec\s+INTEGER NOT NULL CHECK \(max_events_per_sec > 0\)/);
  });

  it("keeps the tail ceilings on the lane, so opening a session cannot raise the lane's worst case", () => {
    const body = tableBody("slate_insight_policies");
    expect(body).toMatch(/max_tail_sample_rate\s+NUMERIC\(6, 5\) NOT NULL/);
    expect(body).toMatch(/max_tail_events_per_sec\s+INTEGER NOT NULL DEFAULT \d+/);
  });

  it("records who opened a tail and why, on an identity that survives offboarding", () => {
    const body = tableBody("slate_insight_live_tail_sessions");
    expect(body).toMatch(
      /opened_by_actor_id\s+UUID REFERENCES apiome\.users\(id\) ON DELETE SET NULL/,
    );
    expect(body).toMatch(/opened_by_actor_name\s+TEXT NOT NULL/);
    expect(body).toMatch(/opened_by_actor_key\s+TEXT NOT NULL/);
    expect(body).toMatch(/reason\s+TEXT NOT NULL/);
  });

  it("orders a tail session's end after its start, so a session cannot close before it opened", () => {
    expect(constraintExpression(
      tableBody("slate_insight_live_tail_sessions"),
      "slate_insight_live_tail_sessions_ordered",
    )).toBe("(ended_at IS NULL OR ended_at >= started_at)");
  });

  /* ---------------------------------------------------------------------- */
  /* Traces, spans and the waterfall                                        */
  /* ---------------------------------------------------------------------- */

  it("shape-constrains trace and span ids, so an export cannot be handed an identifier a collector will reject", () => {
    expect(tableBody("slate_insight_traces")).toMatch(
      /trace_id\s+TEXT NOT NULL CHECK \(trace_id ~ '\^\[0-9a-f\]\{32\}\$'\)/,
    );
    expect(tableBody("slate_insight_trace_spans")).toMatch(
      /span_id\s+TEXT NOT NULL CHECK \(span_id ~ '\^\[0-9a-f\]\{16\}\$'\)/,
    );
  });

  it("stores the sampling rate that kept a trace, so a rare event is distinguishable from a rarely sampled one", () => {
    const body = tableBody("slate_insight_traces");
    expect(body).toMatch(/sample_rate\s+NUMERIC\(6, 5\) NOT NULL/);
    expect(body).toContain("CHECK (sample_rate > 0 AND sample_rate <= 1)");
  });

  it("cascades a span with its trace, the opposite of a function revision and deliberately so", () => {
    // A span of a deleted trace is not evidence of anything, because a waterfall is only meaningful
    // whole — unlike V189's revisions, which exist precisely to outlive what they describe.
    expect(columnDeclaration("slate_insight_trace_spans", "trace_id")).toContain("UUID NOT NULL");
    expect(tableBody("slate_insight_trace_spans")).toContain(
      "REFERENCES apiome.slate_insight_traces(id) ON DELETE CASCADE",
    );
  });

  it("refuses a span that is its own parent, which would loop any waterfall renderer forever", () => {
    expect(constraintExpression(
      tableBody("slate_insight_trace_spans"),
      "slate_insight_trace_spans_not_own_parent",
    )).toBe("(parent_span_ref IS NULL OR parent_span_ref <> span_id)");
  });

  it("stores span timing as offsets, so the rendering cannot disagree with the ordering", () => {
    expect(tableBody("slate_insight_trace_spans")).toMatch(
      /start_offset_ms\s+INTEGER NOT NULL CHECK \(start_offset_ms >= 0\)/,
    );
  });

  it("deliberately does not make a log line's trace_ref a foreign key", () => {
    // Traces expire on a shorter retention than logs, so an FK would delete a line whose trace aged
    // out — and a log line without its trace is still worth reading. Read the declaration and
    // assert what it says, rather than asserting the absence of a hand-written literal.
    const declaration = columnDeclaration("slate_insight_logs", "trace_ref");
    expect(declaration).toContain("UUID");
    expect(declaration).not.toContain("REFERENCES");
    expect(tableBody("slate_insight_logs")).not.toContain("REFERENCES apiome.slate_insight_traces");
  });

  it("gives a trace id one meaning per lane rather than per tenant", () => {
    expect(tableBody("slate_insight_traces")).toContain("UNIQUE (environment_id, trace_id)");
  });

  /* ---------------------------------------------------------------------- */
  /* Usage, budgets and money                                               */
  /* ---------------------------------------------------------------------- */

  it("stores money as NUMERIC with an explicit currency beside it, never as a float", () => {
    for (const [table, column] of [
      ["slate_insight_usage_records", "amount"],
      ["slate_insight_budgets", "amount"],
      ["slate_insight_budget_alerts", "observed_amount"],
    ] as const) {
      expect(columnDeclaration(table, column)).toContain("NUMERIC(20, 6)");
    }
    for (const table of [
      "slate_insight_usage_records",
      "slate_insight_budgets",
      "slate_insight_budget_alerts",
    ]) {
      expect(tableBody(table)).toMatch(/currency\s+TEXT NOT NULL DEFAULT 'USD'/);
      expect(tableBody(table)).toContain("CHECK (currency ~ '^[A-Z]{3}$')");
    }
    // Matched case-sensitively as a type name: the rationale prose says "real traffic", and a
    // case-insensitive check would fail on the migration's own explanation rather than on a float.
    expect(sql).not.toMatch(/\b(DOUBLE PRECISION|FLOAT[48]?|REAL)\b/);
  });

  it("makes overage a stored fact rather than a subtraction the UI and the invoice might perform differently", () => {
    const body = tableBody("slate_insight_usage_records");
    expect(body).toMatch(/included_quantity\s+NUMERIC\(20, 6\) NOT NULL DEFAULT 0/);
    expect(body).toMatch(/overage_quantity\s+NUMERIC\(20, 6\) NOT NULL DEFAULT 0/);
    expect(constraintExpression(body, "slate_insight_usage_records_overage_within_quantity")).toBe(
      "(overage_quantity <= quantity)",
    );
  });

  it("gives a service exactly one usage row per day, so a retry cannot double a total", () => {
    expect(tableBody("slate_insight_usage_records")).toContain(
      "UNIQUE (environment_id, service, usage_date)",
    );
    expect(columnDeclaration("slate_insight_usage_records", "usage_date")).toContain("DATE NOT NULL");
  });

  it("names the five services §29.6 asks for, in usage and in budgets alike", () => {
    for (const table of ["slate_insight_usage_records", "slate_insight_budgets"]) {
      expect(tableBody(table)).toContain("'delivery', 'build', 'function', 'log', 'ai'");
    }
  });

  it("refuses a budget with no threshold, which is a budget that does nothing", () => {
    expect(constraintExpression(
      tableBody("slate_insight_budgets"),
      "slate_insight_budgets_thresholds_present",
    )).toBe("(cardinality(alert_thresholds) > 0)");
  });

  it("refuses a zero threshold, which is crossed by the first cent of spend and stays crossed, so it fires immediately and permanently", () => {
    const check = constraintExpression(
      tableBody("slate_insight_budgets"),
      "slate_insight_budgets_thresholds_bounded",
    );
    // `0 < ALL (...)` rather than a bound on the array as a whole: a single bad member is the
    // entire failure, so the constraint has to reach every element.
    expect(check).toContain("0 < ALL (alert_thresholds)");
  });

  it("refuses a threshold above twice the budget, so an alert nobody will ever see cannot be saved as though it would fire", () => {
    const check = constraintExpression(
      tableBody("slate_insight_budgets"),
      "slate_insight_budgets_thresholds_bounded",
    );
    expect(check).toContain("2.0 >= ALL (alert_thresholds)");
  });

  it("bounds thresholds element-wise on both sides in one named constraint, so neither end can be dropped while the name stays", () => {
    // Asserted as a whole expression as well as by its two halves: an edit that removed one bound
    // would leave the constraint present and correctly named while silently admitting the value it
    // was written to exclude, and a test that only checked for the name would stay green.
    expect(sql).toContain("slate_insight_budgets_thresholds_bounded");
    expect(constraintExpression(
      tableBody("slate_insight_budgets"),
      "slate_insight_budgets_thresholds_bounded",
    )).toBe("(0 < ALL (alert_thresholds) AND 2.0 >= ALL (alert_thresholds))");
  });

  it("keeps the default thresholds inside the bound it declares, so a budget created with no input is not born invalid", () => {
    expect(columnDeclaration("slate_insight_budgets", "alert_thresholds")).toContain(
      "DEFAULT ARRAY[0.800, 1.000]::NUMERIC(4, 3)[]",
    );
  });

  it("fires one alert per budget, threshold and period, so a scheduler retry does not teach operators to ignore it", () => {
    expect(tableBody("slate_insight_budget_alerts")).toContain(
      "UNIQUE (budget_id, threshold, period_start)",
    );
  });

  it("stores the arithmetic behind an alert, so it does not have to be trusted the second time it fires", () => {
    const body = tableBody("slate_insight_budget_alerts");
    expect(body).toMatch(/observed_amount\s+NUMERIC\(20, 6\) NOT NULL/);
    expect(body).toMatch(/budget_amount\s+NUMERIC\(20, 6\) NOT NULL/);
    expect(constraintExpression(body, "slate_insight_budget_alerts_period_ordered")).toBe(
      "(period_end >= period_start)",
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Policy is per lane, versioned and opt-in                               */
  /* ---------------------------------------------------------------------- */

  it("gives a lane exactly one insight policy, with an optimistic-concurrency token", () => {
    const body = tableBody("slate_insight_policies");
    expect(body).toMatch(/environment_id\s+UUID NOT NULL UNIQUE/);
    expect(body).toMatch(/policy_version\s+BIGINT NOT NULL DEFAULT 0/);
  });

  it("opts a lane into collection rather than inheriting it, because the default posture for request data is not to hold it", () => {
    expect(tableBody("slate_insight_policies")).toMatch(
      /telemetry_enabled\s+BOOLEAN NOT NULL DEFAULT FALSE/,
    );
  });

  it("names a collector provider column so attaching one is a data change rather than a migration", () => {
    expect(tableBody("slate_insight_policies")).toMatch(/edge_provider\s+TEXT/);
  });

  it("refuses a synthetic check enabled with no region to run from", () => {
    expect(constraintExpression(
      tableBody("slate_insight_synthetic_checks"),
      "slate_insight_synthetic_checks_enabled_needs_regions",
    )).toBe("(NOT enabled OR cardinality(regions) > 0)");
  });

  it("floors the synthetic probe interval, so a health check cannot be turned into a load generator", () => {
    expect(tableBody("slate_insight_synthetic_checks")).toContain(
      "CHECK (interval_seconds >= 60)",
    );
  });

  /* ---------------------------------------------------------------------- */
  /* Audit is append-only                                                   */
  /* ---------------------------------------------------------------------- */

  it("refuses UPDATE and DELETE on the insights audit at the database", () => {
    expect(sql).toContain("CREATE OR REPLACE FUNCTION apiome.slate_insight_audit_append_only()");
    expect(sql).toContain("BEFORE UPDATE OR DELETE ON apiome.slate_insight_audit");
    expect(sql).toContain("trg_slate_insight_audit_append_only");
    expect(sql).toContain("is append-only: % is not permitted");
    expect(sql).toContain("USING ERRCODE = '23514'");
  });

  it("raises rather than silently doing nothing, so a caller that tries learns it was refused", () => {
    expect(sql).toContain("RAISE EXCEPTION");
    expect(sql).toContain("FOR EACH ROW EXECUTE FUNCTION apiome.slate_insight_audit_append_only()");
  });

  it("scopes audit entries to what they are about, including who exported the evidence", () => {
    const body = tableBody("slate_insight_audit");
    expect(body).toContain("CHECK (subject_kind IN ('policy', 'residency-lane', 'otlp-export',");
    // Reading the evidence is itself audit-worthy: an export is a disclosure, not a page view.
    expect(body).toContain("'export'");
  });

  it("records whether a person or a system acted", () => {
    expect(tableBody("slate_insight_audit")).toContain(
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
