/**
 * The `scale` seed profile (DBP-1.1, #7184): a large, deterministic database for query budgets
 * and plan checks.
 *
 * Every row is generated in PostgreSQL by `INSERT … SELECT … FROM generate_series(…)`, one
 * statement per step, so the database builds in minutes rather than hours. The data is
 * deterministic: a row's id is `md5('apiome-scale:<kind>:<n>')::uuid` and every other column is a
 * pure function of its index `n`, so two runs with the same parameters produce the same rows.
 *
 * Re-running is idempotent and cheap. Each step first checks whether the last row it would write
 * already exists; a complete step is skipped. A step that is incomplete (or whose count grew)
 * inserts the missing rows with `ON CONFLICT DO NOTHING`.
 *
 * Shape (at `--scale-factor 1`, the volume of the 2026-11-22 audit):
 *
 * | table                       | rows      | notes                                           |
 * | --------------------------- | --------- | ----------------------------------------------- |
 * | tenants                     | 200       | tenant 0 (`scale-large`) is the skewed tenant   |
 * | users / tenant_users        | 2,000     | one owner per tenant in tenant_administrators   |
 * | projects                    | 20,000    | 5,000 in the large tenant; 2 % soft-deleted     |
 * | versions                    | 200,000   | 10 per project in a parent chain; last is draft |
 * | properties                  | 60,000    | 3 library properties per project                |
 * | classes                     | 1,000,000 | 20,000 in one version; 5 % soft-deleted         |
 * | class_properties            | 3,100,000 |                                                 |
 * | version_path / path_operation | 600,000 / 1,200,000 |                                     |
 * | mcp_endpoints / versions / capability items | 2,000 / 10,000 / 200,000 |                    |
 * | usage_source / usage_daily  | 5,000 / 500,000 | the large tenant's projects             |
 * | workflow_audit / access_audit | 500,000 / 200,000 |                                       |
 *
 * Every tenant slug starts with `scale-`, every email ends in `@scale.apiome.test`, and users get a
 * password value that is not a bcrypt hash, so no seeded account can sign in.
 */

import { createHash } from "node:crypto";

import type pg from "pg";

import { CliError } from "./errors.js";

/** Row counts of the scale profile. Every field is a whole number ≥ 0 (counts) or ≥ 1 (sizes). */
export type ScaleParams = {
  tenants: number;
  users: number;
  projects: number;
  /** How many of `projects` belong to tenant 0, the skewed "large tenant". */
  largeTenantProjects: number;
  versionsPerProject: number;
  classes: number;
  /** How many of `classes` belong to version 0, the "20k-class version". */
  largeVersionClasses: number;
  classProperties: number;
  paths: number;
  /** Operations; at most five per path (one per method). */
  operations: number;
  mcpEndpoints: number;
  mcpVersionsPerEndpoint: number;
  mcpItemsPerVersion: number;
  usageRows: number;
  workflowAuditRows: number;
  accessAuditRows: number;
};

/** The audit's volume (`--scale-factor 1`). */
export const DEFAULT_SCALE_PARAMS: Readonly<ScaleParams> = Object.freeze({
  tenants: 200,
  users: 2_000,
  projects: 20_000,
  largeTenantProjects: 5_000,
  versionsPerProject: 10,
  classes: 1_000_000,
  largeVersionClasses: 20_000,
  classProperties: 3_100_000,
  paths: 600_000,
  operations: 1_200_000,
  mcpEndpoints: 2_000,
  mcpVersionsPerEndpoint: 5,
  mcpItemsPerVersion: 20,
  usageRows: 500_000,
  workflowAuditRows: 500_000,
  accessAuditRows: 200_000,
});

/** Sizes (per-parent multipliers) that a scale factor leaves alone. */
const SIZE_KEYS: ReadonlyArray<keyof ScaleParams> = [
  "versionsPerProject",
  "mcpVersionsPerEndpoint",
  "mcpItemsPerVersion",
];

/**
 * Steps inserted without user triggers (see {@link ScaleStep.bypassTriggers}). Tenants, projects
 * and versions keep theirs: the free-license and MCP search-document triggers fill rows that the
 * plans under test read.
 */
const BYPASS_TRIGGER_STEPS: ReadonlySet<string> = new Set([
  "classes",
  "class_properties",
  "paths",
  "operations",
  "mcp_capability_items",
  "usage_daily",
  "workflow_audit",
  "access_audit",
]);

/** JSON Schema types of each project's library properties (`properties` rows), in order. */
const PROPERTY_TYPES = ["string", "integer", "boolean"] as const;

/** HTTP methods given to a path's operations, in order. */
const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

/**
 * Scale the default counts by `factor` and apply explicit overrides.
 *
 * Counts are multiplied and rounded (at least 1); per-parent sizes are not. The result is made
 * consistent: at least one user per tenant, the large tenant and the large version no bigger than
 * the whole, and no more than five operations per path.
 *
 * @param factor Multiplier for every count (`1` = the audit's volume). Must be > 0.
 * @param overrides Exact values that replace the scaled ones.
 * @returns The parameters a {@link buildScaleSteps} call takes.
 * @throws CliError When `factor` or an override is not a positive finite number.
 */
export function resolveScaleParams(factor = 1, overrides: Partial<ScaleParams> = {}): ScaleParams {
  if (!Number.isFinite(factor) || factor <= 0) {
    throw new CliError(`--scale-factor must be a positive number (got ${factor}).`, { exitCode: 2 });
  }
  const params = { ...DEFAULT_SCALE_PARAMS } as ScaleParams;
  for (const key of Object.keys(params) as Array<keyof ScaleParams>) {
    if (!SIZE_KEYS.includes(key)) params[key] = Math.max(1, Math.round(params[key] * factor));
  }
  for (const [key, value] of Object.entries(overrides) as Array<[keyof ScaleParams, number]>) {
    if (value === undefined) continue;
    if (!Number.isInteger(value) || value < 1) {
      throw new CliError(`${key} must be a whole number ≥ 1 (got ${value}).`, { exitCode: 2 });
    }
    params[key] = value;
  }
  params.users = Math.max(params.users, params.tenants);
  params.largeTenantProjects = Math.min(params.largeTenantProjects, params.projects);
  params.largeVersionClasses = Math.min(params.largeVersionClasses, params.classes);
  params.operations = Math.min(params.operations, params.paths * METHODS.length);
  return params;
}

/** One generated statement of the profile. */
export type ScaleStep = {
  /** Stable step name, also the label printed by the CLI. */
  name: string;
  /** Table the step fills (schema-qualified). */
  table: string;
  /** Rows the step writes when it runs from empty. */
  rows: number;
  /** Id of the step's last row: when it exists the step is complete and skipped. */
  lastId: string;
  /** The `INSERT … SELECT` statement. */
  sql: string;
  /**
   * Insert with `session_replication_role = replica`, so the table's user triggers do not fire.
   * Set on the bulk revision-content tables, whose row-level content-stamp trigger would update
   * `versions` once per touched revision and turn a minutes-long build into hours. The rows are
   * consistent by construction; their revisions keep `content_stamp = 0`.
   */
  bypassTriggers: boolean;
};

/** SQL expression for the deterministic uuid of row `index` (an SQL expression) of `kind`. */
export function scaleIdSql(kind: string, index: string): string {
  return `md5('apiome-scale:${kind}:' || (${index}))::uuid`;
}

/**
 * The deterministic uuid {@link scaleIdSql} computes, worked out in JavaScript.
 *
 * @param kind Row kind (`tenant`, `project`, …).
 * @param index The row's index.
 * @returns The uuid text PostgreSQL returns for `md5('apiome-scale:<kind>:<index>')::uuid`.
 */
export function scaleId(kind: string, index: number): string {
  const hex = createHash("md5").update(`apiome-scale:${kind}:${index}`).digest("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** SQL for the tenant index that owns project `p` (an SQL expression). */
function tenantOfProject(p: string, params: ScaleParams): string {
  const { largeTenantProjects: large, tenants } = params;
  if (tenants === 1) return "0";
  return `(CASE WHEN ${p} < ${large} THEN 0 ELSE 1 + ((${p}) - ${large}) % ${tenants - 1} END)`;
}

/**
 * The profile's statements, in dependency order.
 *
 * @param params Row counts, normally from {@link resolveScaleParams}.
 * @returns One {@link ScaleStep} per table.
 */
export function buildScaleSteps(params: ScaleParams): ScaleStep[] {
  const id = scaleIdSql;
  const T = params.tenants;
  const versions = params.projects * params.versionsPerProject;
  const vpp = params.versionsPerProject;
  const mcpVersions = params.mcpEndpoints * params.mcpVersionsPerEndpoint;
  const items = mcpVersions * params.mcpItemsPerVersion;
  const usageSources = params.largeTenantProjects;
  const libraryProperties = params.projects * PROPERTY_TYPES.length;
  const ownerOf = (tenantIndex: string): string => id("user", tenantIndex);
  const series = (count: number): string => `generate_series(0, ${count - 1}) AS g(n)`;

  const step = (name: string, table: string, rows: number, kind: string, sql: string): ScaleStep => ({
    name,
    table,
    rows,
    lastId: kind,
    sql: sql.trim().replace(/\n\s+/g, "\n  "),
    bypassTriggers: BYPASS_TRIGGER_STEPS.has(name),
  });

  // The class index → version index mapping: the first `largeVersionClasses` classes sit in
  // version 0; the rest spread round-robin over the other versions.
  const lc = params.largeVersionClasses;
  const versionOfClass = (c: string): string =>
    versions === 1 ? "0" : `(CASE WHEN ${c} < ${lc} THEN 0 ELSE 1 + (${c} - ${lc}) % ${versions - 1} END)`;

  return [
    step("tenants", "apiome.tenants", T, `tenant:${T - 1}`, `
      INSERT INTO apiome.tenants (id, name, slug, description)
      SELECT ${id("tenant", "n")},
             CASE WHEN n = 0 THEN 'Scale large tenant' ELSE 'Scale tenant ' || n END,
             CASE WHEN n = 0 THEN 'scale-large' ELSE 'scale-t' || n END,
             'Generated by apiome-db seed --profile scale.'
        FROM ${series(T)}
      ON CONFLICT DO NOTHING`),
    step("users", "apiome.users", params.users, `user:${params.users - 1}`, `
      INSERT INTO apiome.users (id, name, email, password, verified)
      SELECT ${id("user", "n")}, 'Scale user ' || n, 'scale-user-' || n || '@scale.apiome.test',
             'scale-seed-no-login', true
        FROM ${series(params.users)}
      ON CONFLICT DO NOTHING`),
    step("tenant_users", "apiome.tenant_users", params.users, `tenant_user:${params.users - 1}`, `
      INSERT INTO apiome.tenant_users (id, tenant_id, user_id, status)
      SELECT ${id("tenant_user", "n")}, ${id("tenant", `n % ${T}`)}, ${id("user", "n")}, 'active'
        FROM ${series(params.users)}
      ON CONFLICT DO NOTHING`),
    step("tenant_administrators", "apiome.tenant_administrators", T, `tenant_admin:${T - 1}`, `
      INSERT INTO apiome.tenant_administrators (id, tenant_id, user_id)
      SELECT ${id("tenant_admin", "n")}, ${id("tenant", "n")}, ${ownerOf("n")}
        FROM ${series(T)}
      ON CONFLICT DO NOTHING`),
    step("projects", "apiome.projects", params.projects, `project:${params.projects - 1}`, `
      INSERT INTO apiome.projects (id, tenant_id, creator_id, name, slug, description, deleted_at, created_at)
      SELECT ${id("project", "n")}, ${id("tenant", tenantOfProject("n", params))},
             ${ownerOf(tenantOfProject("n", params))}, 'Scale project ' || n, 'scale-p' || n,
             'Generated project ' || n,
             CASE WHEN n % 50 = 49 THEN timestamptz '2026-06-01' END,
             timestamptz '2026-01-01' + n * interval '1 minute'
        FROM ${series(params.projects)}
      ON CONFLICT DO NOTHING`),
    step("versions", "apiome.versions", versions, `version:${versions - 1}`, `
      INSERT INTO apiome.versions (id, project_id, creator_id, version_id, description, published,
                                   published_at, visibility, parent_version_id, created_at)
      SELECT ${id("version", "n")}, ${id("project", `n / ${vpp}`)},
             ${ownerOf(tenantOfProject(`(n / ${vpp})`, params))}, '1.0.' || (n % ${vpp}),
             'Revision ' || (n % ${vpp}) || ' of project ' || (n / ${vpp}),
             (n % ${vpp}) < ${vpp - 1},
             CASE WHEN (n % ${vpp}) < ${vpp - 1} THEN timestamptz '2026-01-01' + n * interval '1 second' END,
             CASE WHEN (n / ${vpp}) % 4 = 0 AND (n % ${vpp}) < ${vpp - 1}
                  THEN 'public'::apiome.visibility_type ELSE 'private'::apiome.visibility_type END,
             CASE WHEN n % ${vpp} > 0 THEN ${id("version", "n - 1")} END,
             timestamptz '2026-01-01' + n * interval '1 second'
        FROM ${series(versions)}
      ON CONFLICT DO NOTHING`),
    // Three library properties per project (string, integer, boolean); every class property
    // references one, as the null-property_id check requires of a non-$ref property.
    step("properties", "apiome.properties", libraryProperties, `property:${libraryProperties - 1}`, `
      INSERT INTO apiome.properties (id, project_id, name, data)
      SELECT ${id("property", "n")}, ${id("project", `n / ${PROPERTY_TYPES.length}`)},
             'field_' || (ARRAY[${PROPERTY_TYPES.map((t) => `'${t}'`).join(", ")}])[1 + n % ${PROPERTY_TYPES.length}],
             jsonb_build_object('type', (ARRAY[${PROPERTY_TYPES.map((t) => `'${t}'`).join(", ")}])[1 + n % ${PROPERTY_TYPES.length}])
        FROM ${series(libraryProperties)}
      ON CONFLICT DO NOTHING`),
    step("classes", "apiome.classes", params.classes, `class:${params.classes - 1}`, `
      INSERT INTO apiome.classes (id, version_id, name, description, schema, deleted_at)
      SELECT ${id("class", "n")}, ${id("version", versionOfClass("n"))}, 'Class' || n, 'Generated class ' || n,
             jsonb_build_object('type', 'object', 'title', 'Class' || n),
             CASE WHEN n % 20 = 19 THEN timestamptz '2026-06-01' END
        FROM ${series(params.classes)}
      ON CONFLICT DO NOTHING`),
    step("class_properties", "apiome.class_properties", params.classProperties,
      `class_property:${params.classProperties - 1}`, `
      INSERT INTO apiome.class_properties (id, class_id, property_id, name, data)
      SELECT ${id("class_property", "n")}, ${id("class", "c")},
             ${id("property", `(${versionOfClass("c")} / ${vpp}) * ${PROPERTY_TYPES.length} + n % ${PROPERTY_TYPES.length}`)},
             'field' || (n / ${params.classes}),
             jsonb_build_object('type', (ARRAY[${PROPERTY_TYPES.map((t) => `'${t}'`).join(", ")}])[1 + n % ${PROPERTY_TYPES.length}])
        FROM (SELECT n, n % ${params.classes} AS c FROM ${series(params.classProperties)}) AS g
      ON CONFLICT DO NOTHING`),
    step("paths", "apiome.version_path", params.paths, `path:${params.paths - 1}`, `
      INSERT INTO apiome.version_path (id, version_id, pathname)
      SELECT ${id("path", "n")}, ${id("version", `n % ${versions}`)}, '/resources' || n
        FROM ${series(params.paths)}
      ON CONFLICT DO NOTHING`),
    step("operations", "apiome.path_operation", params.operations, `operation:${params.operations - 1}`, `
      INSERT INTO apiome.path_operation (id, version_path_id, operation)
      SELECT ${id("operation", "n")}, ${id("path", `n % ${params.paths}`)},
             (ARRAY[${METHODS.map((m) => `'${m}'`).join(", ")}])[1 + (n / ${params.paths}) % ${METHODS.length}]
        FROM ${series(params.operations)}
      ON CONFLICT DO NOTHING`),
    step("mcp_endpoints", "apiome.mcp_endpoints", params.mcpEndpoints, `mcp_endpoint:${params.mcpEndpoints - 1}`, `
      INSERT INTO apiome.mcp_endpoints (id, tenant_id, creator_id, name, slug, endpoint_url, transport,
                                        visibility, published)
      SELECT ${id("mcp_endpoint", "n")}, ${id("tenant", `n % ${T}`)}, ${ownerOf(`n % ${T}`)},
             'Scale MCP server ' || n, 'scale-mcp-' || n,
             'https://mcp' || n || '.scale.apiome.test/mcp', 'streamable_http',
             CASE WHEN n % 2 = 0 THEN 'public'::apiome.visibility_type ELSE 'private'::apiome.visibility_type END,
             true
        FROM ${series(params.mcpEndpoints)}
      ON CONFLICT DO NOTHING`),
    step("mcp_endpoint_versions", "apiome.mcp_endpoint_versions", mcpVersions, `mcp_version:${mcpVersions - 1}`, `
      INSERT INTO apiome.mcp_endpoint_versions (id, endpoint_id, version_seq, version_tag, server_name,
                                                discovered_at)
      SELECT ${id("mcp_version", "n")}, ${id("mcp_endpoint", `n / ${params.mcpVersionsPerEndpoint}`)},
             1 + n % ${params.mcpVersionsPerEndpoint},
             to_char(timestamp '2026-01-01' + (n % ${params.mcpVersionsPerEndpoint}) * interval '1 day',
                     'YYYY-MM-DD"T"HH24:MI"Z"'),
             'scale-server-' || (n / ${params.mcpVersionsPerEndpoint}),
             timestamptz '2026-01-01' + (n % ${params.mcpVersionsPerEndpoint}) * interval '1 day'
        FROM ${series(mcpVersions)}
      ON CONFLICT DO NOTHING`),
    step("mcp_capability_items", "apiome.mcp_capability_items", items, `mcp_item:${items - 1}`, `
      INSERT INTO apiome.mcp_capability_items (id, version_id, item_type, name, raw, ordinal)
      SELECT ${id("mcp_item", "n")}, ${id("mcp_version", `n / ${params.mcpItemsPerVersion}`)},
             (ARRAY['tool', 'tool', 'resource', 'prompt'])[1 + n % 4],
             'item_' || (n % ${params.mcpItemsPerVersion}),
             jsonb_build_object('name', 'item_' || (n % ${params.mcpItemsPerVersion}),
                                'description', 'Generated capability ' || n),
             n % ${params.mcpItemsPerVersion}
        FROM ${series(items)}
      ON CONFLICT DO NOTHING`),
    step("usage_sources", "apiome.usage_source", usageSources, `usage_source:${usageSources - 1}`, `
      INSERT INTO apiome.usage_source (id, tenant_id, project_id, kind, environment)
      SELECT ${id("usage_source", "n")}, ${id("tenant", "0")}, ${id("project", "n")}, 'otlp', 'production'
        FROM ${series(usageSources)}
      ON CONFLICT DO NOTHING`),
    // The grain is unique per (source, day, operation): each source gets consecutive days, then
    // the next operation key once a year of days is used.
    step("usage_daily", "apiome.usage_daily", params.usageRows, "", `
      INSERT INTO apiome.usage_daily (tenant_id, project_id, source_id, environment, day, operation_key,
                                      status_code, calls, latency_buckets, latency_sum_ms,
                                      latency_max_ms, auth_present_calls, auth_unknown_calls,
                                      versioned_calls, version_unknown_calls, https_calls,
                                      request_bytes, response_bytes)
      SELECT ${id("tenant", "0")}, ${id("project", `n % ${usageSources}`)},
             ${id("usage_source", `n % ${usageSources}`)}, 'production',
             date '2026-01-01' + ((n / ${usageSources}) % 365)::int,
             '/paths/~1resources' || ((n / ${usageSources}) / 365) || '/get',
             200, 10, ARRAY[10,0,0,0,0,0,0,0,0,0,0,0]::bigint[], 100, 20, 10, 0, 10, 0, 10, 1000, 4000
        FROM ${series(params.usageRows)}
      ON CONFLICT DO NOTHING`),
    step("workflow_audit", "apiome.workflow_audit", params.workflowAuditRows, `workflow_audit:${params.workflowAuditRows - 1}`, `
      INSERT INTO apiome.workflow_audit (id, tenant_id, project_id, version_id, action, outcome, actor_id,
                                         created_at)
      SELECT ${id("workflow_audit", "n")}, ${id("tenant", tenantOfProject(`(n % ${params.projects})`, params))},
             ${id("project", `n % ${params.projects}`)},
             ${id("version", `(n % ${params.projects}) * ${vpp}`)},
             (ARRAY['publish', 'branch_create', 'tag_create', 'merge'])[1 + n % 4], 'allowed',
             ${ownerOf(tenantOfProject(`(n % ${params.projects})`, params))},
             timestamptz '2026-01-01' + n * interval '10 seconds'
        FROM ${series(params.workflowAuditRows)}
      ON CONFLICT DO NOTHING`),
    step("access_audit", "apiome.access_audit", params.accessAuditRows, `access_audit:${params.accessAuditRows - 1}`, `
      INSERT INTO apiome.access_audit (id, tenant_id, actor_id, action, target, created_at)
      SELECT ${id("access_audit", "n")}, ${id("tenant", `n % ${T}`)}, ${ownerOf(`n % ${T}`)},
             (ARRAY['role.assign', 'role.revoke', 'member.invite'])[1 + n % 3], 'user:' || n,
             timestamptz '2026-01-01' + n * interval '30 seconds'
        FROM ${series(params.accessAuditRows)}
      ON CONFLICT DO NOTHING`),
  ];
}

/** What {@link applyScaleSeed} did for one step. */
export type ScaleStepResult = {
  name: string;
  table: string;
  rows: number;
  status: "applied" | "skipped" | "planned";
  inserted: number;
  ms: number;
};

/** What {@link applyScaleSeed} did. */
export type ScaleSeedResult = {
  profile: "scale";
  params: ScaleParams;
  steps: ScaleStepResult[];
  totalMs: number;
  dryRun: boolean;
  /** Set when the bulk steps had to run with triggers on (see {@link insertStep}). */
  note?: string;
};

/**
 * Apply the scale profile, one committed statement per step, then `ANALYZE` the filled tables.
 *
 * @param client An open connection (as the database owner).
 * @param params Row counts from {@link resolveScaleParams}.
 * @param opts `dryRun` lists the steps without writing; `onStep` reports progress.
 * @returns Per-step row counts and timings.
 * @throws CliError When a step fails; earlier steps stay committed, so a re-run resumes there.
 */
export async function applyScaleSeed(
  client: pg.Client,
  params: ScaleParams,
  opts: { dryRun?: boolean; onStep?: (result: ScaleStepResult) => void } = {},
): Promise<ScaleSeedResult> {
  const started = Date.now();
  const results: ScaleStepResult[] = [];
  let triggersNote: string | undefined;
  for (const s of buildScaleSteps(params)) {
    const t0 = Date.now();
    let result: ScaleStepResult;
    if (opts.dryRun) {
      result = { name: s.name, table: s.table, rows: s.rows, status: "planned", inserted: 0, ms: 0 };
    } else if (await stepComplete(client, s)) {
      result = { name: s.name, table: s.table, rows: s.rows, status: "skipped", inserted: 0, ms: Date.now() - t0 };
    } else {
      try {
        const res = await insertStep(client, s, (m) => (triggersNote = m));
        await client.query(`ANALYZE ${s.table}`);
        result = {
          name: s.name,
          table: s.table,
          rows: s.rows,
          status: "applied",
          inserted: res.rowCount ?? 0,
          ms: Date.now() - t0,
        };
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        throw new CliError(`Scale seed step "${s.name}" failed: ${message}`, {
          exitCode: 1,
          hint: "Earlier steps are committed; fix the cause and run the same command again to resume.",
        });
      }
    }
    results.push(result);
    opts.onStep?.(result);
  }
  return {
    profile: "scale",
    params,
    steps: results,
    totalMs: Date.now() - started,
    dryRun: Boolean(opts.dryRun),
    ...(triggersNote ? { note: triggersNote } : {}),
  };
}

/**
 * Run one step's statement in its own transaction, without user triggers when the step asks and
 * the role may (`session_replication_role` needs superuser or an explicit grant). Without the
 * privilege the statement runs with triggers on, slower but correct, and `onNote` says so.
 */
async function insertStep(
  client: pg.Client,
  s: ScaleStep,
  onNote: (message: string) => void,
): Promise<pg.QueryResult> {
  await client.query("BEGIN");
  try {
    if (s.bypassTriggers) {
      await client.query("SAVEPOINT replica_role");
      try {
        await client.query("SET LOCAL session_replication_role = replica");
        await client.query("RELEASE SAVEPOINT replica_role");
      } catch {
        await client.query("ROLLBACK TO SAVEPOINT replica_role");
        onNote(
          "This role may not set session_replication_role, so row triggers fired during the bulk steps " +
            "(slower). Run the seed as the database owner or a superuser to build in minutes.",
        );
      }
    }
    const res = await client.query(s.sql);
    await client.query("COMMIT");
    return res;
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  }
}

/**
 * Whether a step's rows are already there: its last row exists (by id), or — for `usage_daily`,
 * which has no id — the large tenant already holds at least the step's row count.
 */
async function stepComplete(client: pg.Client, s: ScaleStep): Promise<boolean> {
  if (s.lastId === "") {
    const res = await client.query(
      `SELECT count(*) >= $1 AS done FROM (SELECT 1 FROM ${s.table} WHERE tenant_id = $2::uuid LIMIT $1) AS t`,
      [s.rows, scaleId("tenant", 0)],
    );
    return Boolean(res.rows[0]?.done);
  }
  const sep = s.lastId.lastIndexOf(":");
  const kind = s.lastId.slice(0, sep);
  const index = Number(s.lastId.slice(sep + 1));
  const res = await client.query(`SELECT EXISTS (SELECT 1 FROM ${s.table} WHERE id = $1::uuid) AS done`, [
    scaleId(kind, index),
  ]);
  return Boolean(res.rows[0]?.done);
}
