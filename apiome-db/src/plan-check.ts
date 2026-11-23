/**
 * Plan check for the hot queries (DBP-1.1, #7184).
 *
 * Runs each query of a query list with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the scale
 * database (`apiome-db seed --profile scale`) and fails when a plan:
 *
 * - scans a table sequentially whose planner row estimate (`pg_class.reltuples`) is above the
 *   row threshold, or
 * - takes longer than the query's time budget.
 *
 * Each query runs inside a transaction that is rolled back, under a statement timeout, so a
 * query list may hold writes and a runaway plan cannot hang the job.
 *
 * A query the audit already found slow carries `known` (the ticket that fixes it). Its violations
 * are reported but do not fail the check, so the nightly job is green on `main` and a fix shows
 * up as "known issue no longer reproduces" in the report.
 *
 * Two per-query fields describe how the application really runs a statement (DBP-1.16, #7199):
 *
 * - `settings` — session settings the application's pool applies (apiome-browse runs with
 *   `jit = off`), set for the query's transaction only.
 * - `allowSeqScan` — relations the statement scans sequentially *by design*, each with the reason
 *   (a scan that stops at a LIMIT, a catalog-wide count that runs once per cache interval). Such a
 *   scan is reported but is not a violation; the time budget still applies.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type pg from "pg";

import { CliError } from "./errors.js";
import { scaleId } from "./seed-scale.js";

/** A query of the list. */
export type HotQuery = {
  /** Stable, unique name (printed in the report). */
  name: string;
  /** Where the query comes from (file and function), for whoever has to fix it. */
  source: string;
  /** The SQL, with `$1`, `$2`, … placeholders. */
  sql: string;
  /**
   * Parameter values. `"scale:<kind>:<n>"` resolves to the seeded row's id
   * (`md5('apiome-scale:<kind>:<n>')::uuid`); `"scale-ids:<kind>:<from>-<to>"` to an array of them.
   */
  params?: unknown[];
  /** Time budget in milliseconds (default: the list's `defaultBudgetMs`). */
  budgetMs?: number;
  /** The query is a known problem: violations are reported, not failed. */
  known?: { issue: string; reason: string };
  /**
   * Session settings to apply for this query (`SET LOCAL`), as the application's pool does —
   * for example `{ "jit": "off" }`. Names are plain setting names; values are bound, not spliced.
   */
  settings?: Record<string, string>;
  /** Relations (`schema.relation`) whose sequential scan is intended, each with the reason. */
  allowSeqScan?: { relation: string; reason: string }[];
};

/** A query list file. */
export type PlanCheckSpec = {
  /** A sequential scan of a table with more estimated rows than this fails. */
  rowThreshold: number;
  /** Time budget for queries that set none, in milliseconds. */
  defaultBudgetMs: number;
  queries: HotQuery[];
};

/** One sequential scan found in a plan. */
export type SeqScan = { relation: string; estimatedRows: number };

/** What the check found for one query. */
export type QueryResult = {
  name: string;
  source: string;
  executionMs: number;
  planningMs: number;
  budgetMs: number;
  /** A one-line outline of the plan, e.g. `Limit > Index Scan on classes`. */
  shape: string;
  sharedHitBlocks: number;
  sharedReadBlocks: number;
  seqScans: SeqScan[];
  /** Sequential scans above the threshold that the query declares as intended, with the reason. */
  allowedSeqScans: string[];
  violations: string[];
  /** `pass`, `fail`, `known` (violations on a known query) or `fixed` (known, no violations). */
  status: "pass" | "fail" | "known" | "fixed";
  known?: { issue: string; reason: string };
};

/** What {@link runPlanCheck} found. */
export type PlanCheckReport = {
  rowThreshold: number;
  results: QueryResult[];
  failed: number;
};

/** The query list shipped with the package (plan-check/hot-queries.json). */
export function defaultQueriesFile(): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.join(here, "..", "plan-check", "hot-queries.json");
}

/**
 * Read and validate a query list.
 *
 * @param file Path of the JSON file.
 * @returns The parsed list.
 * @throws CliError When the file is unreadable or a query is malformed (missing name or SQL,
 *   duplicate name, non-positive budget).
 */
export async function loadPlanCheckSpec(file: string): Promise<PlanCheckSpec> {
  let raw: string;
  try {
    raw = await fs.readFile(file, "utf8");
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`Could not read the query list ${file}: ${message}`, { exitCode: 2 });
  }
  let spec: PlanCheckSpec;
  try {
    spec = JSON.parse(raw) as PlanCheckSpec;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`The query list ${file} is not JSON: ${message}`, { exitCode: 2 });
  }
  validateSpec(spec, file);
  return spec;
}

/** Throw a {@link CliError} naming the first problem in `spec`. */
export function validateSpec(spec: PlanCheckSpec, file = "query list"): void {
  const fail = (message: string): never => {
    throw new CliError(`${file}: ${message}`, { exitCode: 2 });
  };
  if (!Number.isFinite(spec.rowThreshold) || spec.rowThreshold < 0) fail("rowThreshold must be ≥ 0");
  if (!Number.isFinite(spec.defaultBudgetMs) || spec.defaultBudgetMs <= 0) fail("defaultBudgetMs must be > 0");
  if (!Array.isArray(spec.queries) || spec.queries.length === 0) fail("queries must be a non-empty list");
  const seen = new Set<string>();
  for (const q of spec.queries) {
    if (!q.name || typeof q.sql !== "string" || q.sql.trim() === "") fail(`query ${JSON.stringify(q.name)} needs a name and sql`);
    if (seen.has(q.name)) fail(`duplicate query name ${q.name}`);
    seen.add(q.name);
    if (q.budgetMs !== undefined && !(q.budgetMs > 0)) fail(`${q.name}: budgetMs must be > 0`);
    if (q.known && (!q.known.issue || !q.known.reason)) fail(`${q.name}: known needs an issue and a reason`);
    for (const [setting, value] of Object.entries(q.settings ?? {})) {
      if (!/^[a-z_][a-z0-9_.]*$/.test(setting) || typeof value !== "string") {
        fail(`${q.name}: settings must map a setting name to a string value (got ${JSON.stringify(setting)})`);
      }
    }
    for (const allowed of q.allowSeqScan ?? []) {
      if (!allowed?.relation || !allowed.reason) fail(`${q.name}: allowSeqScan needs a relation and a reason`);
    }
  }
}

/**
 * Turn `scale:` parameter references into the seeded ids.
 *
 * @param value A parameter from the query list.
 * @returns The value to bind.
 * @throws CliError For a malformed `scale-ids:` range.
 */
export function resolveParam(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const one = /^scale:([a-z_]+):(\d+)$/.exec(value);
  if (one) return scaleId(one[1] as string, Number(one[2]));
  const many = /^scale-ids:([a-z_]+):(\d+)-(\d+)$/.exec(value);
  if (many) {
    const from = Number(many[2]);
    const to = Number(many[3]);
    if (to < from || to - from > 10_000) throw new CliError(`Bad id range in parameter ${value}.`, { exitCode: 2 });
    return Array.from({ length: to - from + 1 }, (_, i) => scaleId(many[1] as string, from + i));
  }
  return value;
}

/** A plan node of `EXPLAIN (FORMAT JSON)` output (only the fields the check reads). */
type PlanNode = {
  "Node Type": string;
  "Relation Name"?: string;
  Schema?: string;
  "Index Name"?: string;
  "Shared Hit Blocks"?: number;
  "Shared Read Blocks"?: number;
  Plans?: PlanNode[];
};

/** The top-level object of `EXPLAIN (ANALYZE, FORMAT JSON)` output. */
export type ExplainOutput = { Plan: PlanNode; "Execution Time": number; "Planning Time": number };

/** Every node of a plan tree, depth first. */
function walk(node: PlanNode, out: PlanNode[] = []): PlanNode[] {
  out.push(node);
  for (const child of node.Plans ?? []) walk(child, out);
  return out;
}

/** `schema.relation` of a scan node. */
function relationOf(node: PlanNode): string | undefined {
  if (!node["Relation Name"]) return undefined;
  return `${node.Schema ?? "apiome"}.${node["Relation Name"]}`;
}

/** The schema-qualified relations a plan reads. */
export function relationsOf(explain: ExplainOutput): string[] {
  return [...new Set(walk(explain.Plan).map(relationOf).filter((r): r is string => Boolean(r)))];
}

/**
 * A one-line outline of a plan: its node types, depth first, with the table or index of scans.
 * Up to `limit` nodes; the rest are counted.
 */
export function planShape(explain: ExplainOutput, limit = 8): string {
  const parts = walk(explain.Plan).map((node) => {
    const target = node["Index Name"] ?? node["Relation Name"];
    return target ? `${node["Node Type"]} on ${target}` : node["Node Type"];
  });
  const head = parts.slice(0, limit).join(" > ");
  return parts.length > limit ? `${head} > … (${parts.length - limit} more)` : head;
}

/**
 * Judge one plan against the row threshold and the time budget.
 *
 * @param query The query the plan is for.
 * @param explain Its `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` output.
 * @param estimatedRows Planner row estimates by `schema.relation`.
 * @param spec The list's thresholds.
 * @returns The query's result.
 */
export function judgePlan(
  query: HotQuery,
  explain: ExplainOutput,
  estimatedRows: Record<string, number>,
  spec: Pick<PlanCheckSpec, "rowThreshold" | "defaultBudgetMs">,
): QueryResult {
  const budgetMs = query.budgetMs ?? spec.defaultBudgetMs;
  const nodes = walk(explain.Plan);
  const seqScans: SeqScan[] = nodes
    .filter((n) => n["Node Type"] === "Seq Scan" || n["Node Type"] === "Parallel Seq Scan")
    .map((n) => {
      const relation = relationOf(n) ?? "?";
      return { relation, estimatedRows: Math.round(estimatedRows[relation] ?? 0) };
    });
  const allowed = new Map((query.allowSeqScan ?? []).map((a) => [a.relation, a.reason]));
  const allowedSeqScans: string[] = [];
  const violations: string[] = [];
  for (const scan of seqScans) {
    if (scan.estimatedRows <= spec.rowThreshold) continue;
    const reason = allowed.get(scan.relation);
    if (reason !== undefined) {
      const note = `sequential scan of ${scan.relation} by design: ${reason}`;
      if (!allowedSeqScans.includes(note)) allowedSeqScans.push(note);
    } else {
      violations.push(
        `sequential scan of ${scan.relation} (~${scan.estimatedRows.toLocaleString("en-US")} rows > ${spec.rowThreshold.toLocaleString("en-US")})`,
      );
    }
  }
  const executionMs = explain["Execution Time"];
  if (executionMs > budgetMs) violations.push(`${executionMs.toFixed(2)} ms > budget ${budgetMs} ms`);
  const status: QueryResult["status"] = query.known
    ? violations.length > 0
      ? "known"
      : "fixed"
    : violations.length > 0
      ? "fail"
      : "pass";
  return {
    name: query.name,
    source: query.source,
    executionMs: Math.round(executionMs * 1000) / 1000,
    planningMs: Math.round(explain["Planning Time"] * 1000) / 1000,
    budgetMs,
    shape: planShape(explain),
    sharedHitBlocks: explain.Plan["Shared Hit Blocks"] ?? 0,
    sharedReadBlocks: explain.Plan["Shared Read Blocks"] ?? 0,
    seqScans,
    allowedSeqScans,
    violations,
    status,
    ...(query.known ? { known: query.known } : {}),
  };
}

/**
 * Run the plan check.
 *
 * @param client An open connection to the scale database.
 * @param spec The query list.
 * @param opts `runs`: executions per query, the fastest counts (default 2: the first warms the
 *   cache). `timeoutMs`: statement timeout per execution (default 60 s). `only`: query names to run.
 * @returns One result per query.
 */
export async function runPlanCheck(
  client: pg.Client,
  spec: PlanCheckSpec,
  opts: { runs?: number; timeoutMs?: number; only?: string[] } = {},
): Promise<PlanCheckReport> {
  const runs = Math.max(1, opts.runs ?? 2);
  const timeoutMs = Math.max(1, Math.round(opts.timeoutMs ?? 60_000));
  const queries = opts.only?.length ? spec.queries.filter((q) => opts.only?.includes(q.name)) : spec.queries;
  const results: QueryResult[] = [];
  for (const query of queries) {
    const params = (query.params ?? []).map(resolveParam);
    let best: ExplainOutput | undefined;
    for (let i = 0; i < runs; i += 1) {
      const explain = await explainOnce(client, query, params, timeoutMs);
      if (!best || explain["Execution Time"] < best["Execution Time"]) best = explain;
    }
    const explain = best as ExplainOutput;
    results.push(judgePlan(query, explain, await estimatedRowsFor(client, relationsOf(explain)), spec));
  }
  return { rowThreshold: spec.rowThreshold, results, failed: results.filter((r) => r.status === "fail").length };
}

/** One `EXPLAIN ANALYZE` of `query` in a rolled-back transaction. */
async function explainOnce(
  client: pg.Client,
  query: HotQuery,
  params: unknown[],
  timeoutMs: number,
): Promise<ExplainOutput> {
  await client.query("BEGIN");
  try {
    await client.query(`SET LOCAL statement_timeout = ${timeoutMs}`);
    for (const [setting, value] of Object.entries(query.settings ?? {})) {
      await client.query("SELECT set_config($1, $2, true)", [setting, value]);
    }
    const res = await client.query(`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ${query.sql}`, params);
    const plan = (res.rows[0] as Record<string, unknown>)["QUERY PLAN"];
    const parsed = (typeof plan === "string" ? JSON.parse(plan) : plan) as ExplainOutput[];
    return parsed[0] as ExplainOutput;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`Plan check query "${query.name}" failed: ${message}`, { exitCode: 1 });
  } finally {
    await client.query("ROLLBACK");
  }
}

/** `pg_class.reltuples` for each `schema.relation`. */
async function estimatedRowsFor(client: pg.Client, relations: string[]): Promise<Record<string, number>> {
  if (relations.length === 0) return {};
  const res = await client.query(
    `SELECT n.nspname || '.' || c.relname AS rel, GREATEST(c.reltuples, 0)::float8 AS rows
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname || '.' || c.relname = ANY($1::text[])`,
    [relations],
  );
  return Object.fromEntries(res.rows.map((r: { rel: string; rows: number }) => [r.rel, Number(r.rows)]));
}

/**
 * The report as a Markdown table (for the job summary).
 *
 * @param report What {@link runPlanCheck} returned.
 * @returns Markdown text.
 */
export function reportMarkdown(report: PlanCheckReport): string {
  const icon = { pass: "pass", fail: "**FAIL**", known: "known", fixed: "fixed?" } as const;
  const lines = [
    `### Plan check — ${report.results.length} queries, ${report.failed} failed`,
    "",
    `Sequential scans of tables above ${report.rowThreshold.toLocaleString("en-US")} estimated rows fail.`,
    "",
    "| query | status | time (ms) | budget (ms) | buffers hit / read | plan | notes |",
    "| --- | --- | ---: | ---: | ---: | --- | --- |",
  ];
  for (const r of report.results) {
    const notes = [
      ...r.violations,
      ...r.allowedSeqScans,
      ...(r.known ? [`${r.known.issue}: ${r.known.reason}`] : []),
      ...(r.status === "fixed" ? ["known issue no longer reproduces — drop `known`"] : []),
    ].join("; ");
    lines.push(
      `| ${r.name} | ${icon[r.status]} | ${r.executionMs.toFixed(2)} | ${r.budgetMs} | ${r.sharedHitBlocks} / ${r.sharedReadBlocks} | ${r.shape.replaceAll("|", "\\|")} | ${notes.replaceAll("|", "\\|")} |`,
    );
  }
  return `${lines.join("\n")}\n`;
}
