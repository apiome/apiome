/**
 * Backup/restore engine: the I/O and database side of the backup feature.
 *
 * The pure, exhaustively-tested logic lives in sibling modules (`crypto`, `manifest`, `retention`,
 * `pitr`). This file orchestrates them against the filesystem, the `pg` client, and `pg_dump`:
 *
 *   - exportLogicalData  — query the scoped event/snapshot model into a JSON dataset.
 *   - writeBackup        — serialize → optionally encrypt → write artifact + manifest (+ off-site).
 *   - createFullBackup   — whole-cluster pg_dump safety net (encrypted, off-site, manifested).
 *   - listBackups        — read the manifest sidecars in a directory.
 *   - loadDataset        — read + decrypt + parse a logical artifact for restore/drill.
 *   - restoreToSandbox   — fold events as-of a point and materialize them into a sandbox schema.
 *   - pruneBackups       — enforce a retention policy on a backup directory.
 *   - runDrill           — create → restore-to-sandbox → verify → measure RPO/RTO → tear down.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";

import type pg from "pg";

import { buildPgConfig, resolveTenant, type ConnectionOptions } from "../db.js";
import { CliError } from "../errors.js";
import { isUuid } from "../util.js";
import { decryptArtifact, encryptArtifact, isEncryptedArtifact, normalizeKey } from "./crypto.js";
import {
  buildManifest,
  parseManifest,
  serializeManifest,
  verifyArtifactIntegrity,
  type BackupKind,
  type BackupManifest,
} from "./manifest.js";
import { selectExpired, type RetentionPolicy } from "./retention.js";
import { foldEventsAsOf, summarizeDrill, type DataEvent, type DrillSummary } from "./pitr.js";

const execFileAsync = promisify(execFile);

/** Default directory for backup artifacts (override with --out / APIOME_BACKUP_DIR). */
export function defaultBackupDir(): string {
  const dir = process.env.APIOME_BACKUP_DIR?.trim();
  return dir && dir !== "" ? dir : path.resolve(process.cwd(), "backups");
}

/** Optional off-site mirror directory (APIOME_BACKUP_OFFSITE_DIR or --offsite). */
export function defaultOffsiteDir(): string | undefined {
  const dir = process.env.APIOME_BACKUP_OFFSITE_DIR?.trim();
  return dir && dir !== "" ? dir : undefined;
}

/**
 * Resolve the 32-byte backup encryption key from a key file or env. Returns null when neither is
 * configured (caller decides whether to require it).
 */
export async function resolveBackupKey(keyFile?: string): Promise<Buffer | null> {
  if (keyFile) {
    let raw: Buffer;
    try {
      raw = await fs.readFile(keyFile);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new CliError(`Could not read encryption key file ${keyFile}: ${message}`, {
        exitCode: 2,
      });
    }
    return normalizeKey(raw);
  }
  const env = process.env.APIOME_BACKUP_KEY?.trim();
  if (env && env !== "") return normalizeKey(env);
  return null;
}

// ─────────────────────────────── scope ───────────────────────────────

export type ResolvedScope = {
  kind: BackupKind;
  tenantId: string | null;
  tenantLabel: string | null;
  projectId: string | null;
  projectLabel: string | null;
};

/** Resolve a tenant (and optional project) reference into ids/labels for a scoped backup. */
export async function resolveScope(
  client: pg.Client,
  ref: { tenant?: string; project?: string },
): Promise<ResolvedScope> {
  if (!ref.tenant) {
    return { kind: "full", tenantId: null, tenantLabel: null, projectId: null, projectLabel: null };
  }
  const tenant = await resolveTenant(client, ref.tenant);
  if (!ref.project) {
    return {
      kind: "tenant",
      tenantId: tenant.id,
      tenantLabel: tenant.slug,
      projectId: null,
      projectLabel: null,
    };
  }
  const value = ref.project.trim();
  const query = isUuid(value)
    ? "SELECT id, slug FROM apiome.projects WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL"
    : "SELECT id, slug FROM apiome.projects WHERE slug = $1 AND tenant_id = $2 AND deleted_at IS NULL";
  const res = await client.query<{ id: string; slug: string }>(query, [value, tenant.id]);
  const project = res.rows[0];
  if (!project) throw new CliError(`Project not found in tenant ${tenant.slug}: ${ref.project}`);
  return {
    kind: "project",
    tenantId: tenant.id,
    tenantLabel: tenant.slug,
    projectId: project.id,
    projectLabel: project.slug,
  };
}

// ──────────────────────────── logical export ──────────────────────────

/** The JSON body of a logical (tenant/project) backup. */
export type LogicalDataset = {
  scope: ResolvedScope;
  exportedAt: string;
  classSchemas: Record<string, unknown>[];
  events: DataEvent[];
  snapshots: Record<string, unknown>[];
};

type DataRecordRow = {
  id: string;
  record_id: string;
  class_schema_id: string;
  action: DataEvent["action"];
  record_sequence: number;
  data: Record<string, unknown> | null;
  tenant_id: string;
  created_at: string;
  created_by: string | null;
};

/**
 * Export the event/snapshot model for a scope into a dataset. Tenant scope filters by
 * `tenant_id`; project scope additionally joins `class_schema → versions` on `project_id`.
 */
export async function exportLogicalData(
  client: pg.Client,
  scope: ResolvedScope,
): Promise<{ dataset: LogicalDataset; rpoMarker: string | null }> {
  if (scope.kind === "full") {
    throw new CliError("exportLogicalData requires a tenant or project scope.");
  }
  const projectFilter = scope.projectId
    ? "AND cs.version_id IN (SELECT id FROM apiome.versions WHERE project_id = $2)"
    : "";
  const params = scope.projectId ? [scope.tenantId, scope.projectId] : [scope.tenantId];

  const classSchemas = await client.query<Record<string, unknown>>(
    `SELECT cs.* FROM apiome.class_schema cs
       WHERE cs.version_id IN (SELECT id FROM apiome.versions WHERE project_id IN (
         SELECT id FROM apiome.projects WHERE tenant_id = $1
       ))
       ${scope.projectId ? "AND cs.version_id IN (SELECT id FROM apiome.versions WHERE project_id = $2)" : ""}`,
    params,
  );

  const records = await client.query<DataRecordRow>(
    `SELECT dr.id, dr.record_id, dr.class_schema_id, dr.action, dr.record_sequence,
            dr.data, dr.tenant_id, dr.created_at, dr.created_by
       FROM apiome.data_record dr
       ${scope.projectId ? "JOIN apiome.class_schema cs ON cs.id = dr.class_schema_id" : ""}
       WHERE dr.tenant_id = $1 ${projectFilter}
       ORDER BY dr.record_id, dr.record_sequence`,
    params,
  );

  const snapshots = await client.query<Record<string, unknown>>(
    `SELECT ds.* FROM apiome.data_snapshot ds
       ${scope.projectId ? "JOIN apiome.class_schema cs ON cs.id = ds.class_schema_id" : ""}
       WHERE ds.tenant_id = $1 ${projectFilter}`,
    params,
  );

  const events: DataEvent[] = records.rows.map((r) => ({
    recordId: r.record_id,
    recordSequence: r.record_sequence,
    action: r.action,
    data: r.data,
    createdAt: typeof r.created_at === "string" ? r.created_at : new Date(r.created_at).toISOString(),
  }));

  let rpoMarker: string | null = null;
  for (const event of events) {
    const iso = event.createdAt instanceof Date ? event.createdAt.toISOString() : event.createdAt;
    if (rpoMarker === null || iso > rpoMarker) rpoMarker = iso;
  }

  const dataset: LogicalDataset = {
    scope,
    exportedAt: new Date().toISOString(),
    classSchemas: classSchemas.rows,
    events,
    snapshots: snapshots.rows,
  };
  return { dataset, rpoMarker };
}

// ──────────────────────────── write / list ────────────────────────────

export type WriteBackupOptions = {
  dir: string;
  offsiteDir?: string;
  id: string;
  kind: BackupKind;
  tenant?: string | null;
  project?: string | null;
  createdAt: string;
  rpoMarker?: string | null;
  /** Plaintext backup body (a serialized dataset, or a pg_dump archive). */
  body: Buffer;
  /** Encryption key, or null to write unencrypted. */
  key: Buffer | null;
  /** Row counts to record in the manifest. */
  tableCounts?: Record<string, number>;
  /** Artifact filename extension stem (".json" logical, ".dump" for pg_dump). */
  extension: string;
};

/** Write an artifact + manifest to `dir`, mirroring to `offsiteDir` when given. */
export async function writeBackup(opts: WriteBackupOptions): Promise<BackupManifest> {
  await fs.mkdir(opts.dir, { recursive: true });
  const encrypted = opts.key !== null;
  const artifactName = `${opts.id}${opts.extension}${encrypted ? ".enc" : ""}`;
  const artifactBytes = encrypted ? encryptArtifact(opts.body, opts.key as Buffer) : opts.body;

  const manifest = buildManifest({
    id: opts.id,
    kind: opts.kind,
    tenant: opts.tenant ?? null,
    project: opts.project ?? null,
    createdAt: opts.createdAt,
    rpoMarker: opts.rpoMarker ?? null,
    artifact: artifactName,
    artifactBytes,
    encrypted,
    tableCounts: opts.tableCounts,
  });
  const manifestName = `${opts.id}.manifest.json`;

  await fs.writeFile(path.join(opts.dir, artifactName), artifactBytes);
  await fs.writeFile(path.join(opts.dir, manifestName), serializeManifest(manifest));

  if (opts.offsiteDir) {
    await fs.mkdir(opts.offsiteDir, { recursive: true });
    await fs.writeFile(path.join(opts.offsiteDir, artifactName), artifactBytes);
    await fs.writeFile(path.join(opts.offsiteDir, manifestName), serializeManifest(manifest));
  }
  return manifest;
}

/** Read every `*.manifest.json` in `dir`, newest first. Missing dir → empty list. */
export async function listBackups(dir: string): Promise<BackupManifest[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(dir);
  } catch (err) {
    if ((err as { code?: string }).code === "ENOENT") return [];
    throw err;
  }
  const manifests: BackupManifest[] = [];
  for (const name of entries.filter((n) => n.endsWith(".manifest.json"))) {
    const json = await fs.readFile(path.join(dir, name), "utf8");
    manifests.push(parseManifest(json));
  }
  return manifests.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

/** Load and decrypt a logical dataset artifact, verifying integrity against its manifest. */
export async function loadDataset(
  dir: string,
  manifest: BackupManifest,
  key: Buffer | null,
): Promise<LogicalDataset> {
  const artifactBytes = await fs.readFile(path.join(dir, manifest.artifact));
  if (!verifyArtifactIntegrity(manifest, artifactBytes)) {
    throw new CliError(`Backup artifact ${manifest.artifact} failed its SHA-256 integrity check.`, {
      hint: "The artifact is corrupt or was modified after the manifest was written.",
    });
  }
  let plaintext: Buffer = artifactBytes;
  if (manifest.encrypted || isEncryptedArtifact(artifactBytes)) {
    if (key === null) {
      throw new CliError("This backup is encrypted; an encryption key is required to read it.", {
        hint: "Pass --encrypt-key-file <path> or set APIOME_BACKUP_KEY.",
        exitCode: 2,
      });
    }
    plaintext = decryptArtifact(artifactBytes, key);
  }
  if (manifest.kind === "full") {
    throw new CliError("Cannot load a full pg_dump backup as a logical dataset; restore with psql/pg_restore.");
  }
  try {
    return JSON.parse(plaintext.toString("utf8")) as LogicalDataset;
  } catch {
    throw new CliError("Backup dataset is not valid JSON after decryption.");
  }
}

// ──────────────────────────── pg_dump (full) ──────────────────────────

/** Options controlling the `pg_dump` archive format. */
export type PgDumpFormat = "custom" | "plain";

/** Build the `pg_dump` argument vector and environment from connection options. */
export function pgDumpInvocation(
  opts: ConnectionOptions,
  format: PgDumpFormat = "custom",
): { args: string[]; env: NodeJS.ProcessEnv } {
  const cfg = buildPgConfig(opts);
  // Custom format (-Fc) is compressed and restorable with pg_restore; plain is a portable .sql
  // script that diffs cleanly line-by-line (used by `backup dump`).
  const args = [`--format=${format}`, "--no-owner", "--no-privileges"];
  const env: NodeJS.ProcessEnv = { ...process.env };
  if (cfg.connectionString) {
    args.push(`--dbname=${cfg.connectionString}`);
  } else {
    if (cfg.host) args.push(`--host=${String(cfg.host)}`);
    if (cfg.port) args.push(`--port=${String(cfg.port)}`);
    if (cfg.user) args.push(`--username=${String(cfg.user)}`);
    if (cfg.database) args.push(`--dbname=${String(cfg.database)}`);
    if (cfg.password) env.PGPASSWORD = String(cfg.password);
  }
  return { args, env };
}

/** Run `pg_dump` and return the archive bytes. Surfaces a friendly error if pg_dump is absent. */
export async function runPgDump(
  opts: ConnectionOptions,
  format: PgDumpFormat = "custom",
): Promise<Buffer> {
  const { args, env } = pgDumpInvocation(opts, format);
  try {
    const { stdout } = await execFileAsync("pg_dump", args, {
      env,
      encoding: "buffer",
      maxBuffer: 1024 * 1024 * 1024, // 1 GiB
    });
    return stdout as Buffer;
  } catch (err) {
    const e = err as { code?: string; stderr?: Buffer | string };
    if (e.code === "ENOENT") {
      throw new CliError("pg_dump was not found on PATH.", {
        hint: "Install the PostgreSQL client tools (e.g. `apt install postgresql-client`).",
        exitCode: 2,
      });
    }
    const stderr = e.stderr ? Buffer.from(e.stderr).toString("utf8").trim() : "";
    throw new CliError(`pg_dump failed${stderr ? `: ${stderr}` : "."}`);
  }
}

// ──────────────────────────── restore / sandbox ───────────────────────

/** Quote a Postgres identifier for safe interpolation. */
function quoteIdent(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}

/** Validate an operator-supplied sandbox schema name (defends against injection / clobbering apiome). */
export function assertSafeSandboxName(name: string): void {
  if (!/^[a-z_][a-z0-9_]{0,48}$/.test(name)) {
    throw new CliError(
      `Invalid sandbox schema name "${name}" (use lowercase letters, digits, underscores).`,
    );
  }
  if (name === "apiome" || name === "public") {
    throw new CliError(`Refusing to use "${name}" as a sandbox schema (it is a live schema).`);
  }
}

export type RestoreResult = {
  sandboxSchema: string;
  recordsRestored: number;
  deletedCount: number;
  eventsApplied: number;
  asOf: string | null;
};

/**
 * Restore a logical dataset into an isolated sandbox schema by folding its events as of `asOf`
 * (null = latest). Creates `<schema>.pitr_records` and inserts the reconstructed live records, so a
 * recovery can be inspected before being promoted over live data. Never writes to `apiome`.
 */
export async function restoreToSandbox(
  client: pg.Client,
  sandboxSchema: string,
  dataset: LogicalDataset,
  asOf: Date | null,
): Promise<RestoreResult> {
  assertSafeSandboxName(sandboxSchema);
  const folded = foldEventsAsOf(dataset.events, asOf);
  const schema = quoteIdent(sandboxSchema);

  await client.query("BEGIN");
  try {
    await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);
    await client.query(`CREATE SCHEMA ${schema}`);
    await client.query(
      `CREATE TABLE ${schema}.pitr_records (
         record_id UUID PRIMARY KEY,
         data JSONB NOT NULL,
         last_sequence INTEGER NOT NULL,
         last_event_at TIMESTAMPTZ NOT NULL
       )`,
    );
    for (const rec of folded.records) {
      await client.query(
        `INSERT INTO ${schema}.pitr_records (record_id, data, last_sequence, last_event_at)
         VALUES ($1, $2, $3, $4)`,
        [rec.recordId, JSON.stringify(rec.data), rec.lastSequence, rec.lastEventAt],
      );
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  }
  return {
    sandboxSchema,
    recordsRestored: folded.records.length,
    deletedCount: folded.deletedCount,
    eventsApplied: folded.eventsApplied,
    asOf: asOf === null ? null : asOf.toISOString(),
  };
}

/** Drop a sandbox schema created by `restoreToSandbox` (used by drills / cleanup). */
export async function dropSandbox(client: pg.Client, sandboxSchema: string): Promise<void> {
  assertSafeSandboxName(sandboxSchema);
  await client.query(`DROP SCHEMA IF EXISTS ${quoteIdent(sandboxSchema)} CASCADE`);
}

// ──────────────────────────────── prune ───────────────────────────────

export type PruneResult = { pruned: string[]; kept: number };

/** Delete artifacts + manifests in `dir` that have expired under `policy`. */
export async function pruneBackups(
  dir: string,
  policy: RetentionPolicy,
  now: Date,
): Promise<PruneResult> {
  const backups = await listBackups(dir);
  const expired = selectExpired(backups, policy, now);
  const expiredIds = new Set(expired.map((b) => b.id));
  for (const manifest of expired) {
    await fs.rm(path.join(dir, manifest.artifact), { force: true });
    await fs.rm(path.join(dir, `${manifest.id}.manifest.json`), { force: true });
  }
  return { pruned: expired.map((b) => b.id), kept: backups.length - expiredIds.size };
}

// ──────────────────────────────── drill ───────────────────────────────

export type DrillResult = {
  backupId: string;
  restore: RestoreResult;
  summary: DrillSummary;
};

/**
 * Run a disaster-recovery drill against an existing logical backup: load it into a throwaway
 * sandbox, verify integrity + row counts, measure RPO/RTO, then tear the sandbox down. The backup
 * artifact and live `apiome` data are never modified.
 */
export async function runDrill(
  client: pg.Client,
  opts: {
    dir: string;
    manifest: BackupManifest;
    key: Buffer | null;
    sandboxSchema: string;
    asOf: Date | null;
    startedAt: Date;
    now: Date;
    rtoTargetSeconds?: number;
    rpoTargetSeconds?: number;
  },
): Promise<DrillResult> {
  const dataset = await loadDataset(opts.dir, opts.manifest, opts.key);
  let restore: RestoreResult;
  try {
    restore = await restoreToSandbox(client, opts.sandboxSchema, dataset, opts.asOf);
    // Verification: the materialized row count must match the fold result we just inserted.
    const countRes = await client.query<{ count: string }>(
      `SELECT count(*)::text AS count FROM ${quoteIdent(opts.sandboxSchema)}.pitr_records`,
    );
    const materialized = Number(countRes.rows[0]?.count ?? "0");
    const verified = materialized === restore.recordsRestored;
    const summary = summarizeDrill({
      startedAt: opts.startedAt,
      finishedAt: opts.now,
      rpoMarker: opts.manifest.rpoMarker,
      recordsRestored: restore.recordsRestored,
      verified,
      rtoTargetSeconds: opts.rtoTargetSeconds,
      rpoTargetSeconds: opts.rpoTargetSeconds,
    });
    return { backupId: opts.manifest.id, restore, summary };
  } finally {
    await dropSandbox(client, opts.sandboxSchema);
  }
}

/** Serialize a logical dataset to a UTF-8 buffer for writing. */
export function serializeDataset(dataset: LogicalDataset): Buffer {
  return Buffer.from(`${JSON.stringify(dataset, null, 2)}\n`, "utf8");
}

// ──────────────────────────── create (top level) ──────────────────────

export type CreateBackupArtifactsOptions = {
  scope: ResolvedScope;
  id: string;
  dir: string;
  offsiteDir?: string;
  key: Buffer | null;
  createdAt: string;
};

/**
 * Top-level create: branch on scope. `full` runs pg_dump and stores the archive; `tenant`/
 * `project` export the event/snapshot model to a JSON dataset. Both are encrypted (when a key is
 * given), written with a manifest, and mirrored off-site.
 */
export async function createBackupArtifacts(
  client: pg.Client,
  conn: ConnectionOptions,
  opts: CreateBackupArtifactsOptions,
): Promise<BackupManifest> {
  if (opts.scope.kind === "full") {
    const body = await runPgDump(conn);
    return writeBackup({
      dir: opts.dir,
      offsiteDir: opts.offsiteDir,
      id: opts.id,
      kind: "full",
      tenant: null,
      project: null,
      createdAt: opts.createdAt,
      rpoMarker: opts.createdAt,
      body,
      key: opts.key,
      extension: ".dump",
    });
  }

  const { dataset, rpoMarker } = await exportLogicalData(client, opts.scope);
  return writeBackup({
    dir: opts.dir,
    offsiteDir: opts.offsiteDir,
    id: opts.id,
    kind: opts.scope.kind,
    tenant: opts.scope.tenantLabel,
    project: opts.scope.projectLabel,
    createdAt: opts.createdAt,
    rpoMarker,
    body: serializeDataset(dataset),
    key: opts.key,
    tableCounts: {
      class_schema: dataset.classSchemas.length,
      data_record: dataset.events.length,
      data_snapshot: dataset.snapshots.length,
    },
    extension: ".json",
  });
}
