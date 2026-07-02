/**
 * `backup` command handlers — thin glue between the Commander layer (cli.ts) and the engine.
 *
 * Each handler resolves options, calls the engine, and emits mode-aware output (human tables to
 * stdout / notes to stderr, or JSON with `--json`), mirroring the migrate/seed handlers.
 */

import type pg from "pg";

import type { ConnectionOptions } from "../db.js";
import { CliError } from "../errors.js";
import { note, printRecord, printRows, type OutputMode } from "../output.js";
import {
  createBackupArtifacts,
  defaultBackupDir,
  defaultOffsiteDir,
  listBackups,
  loadDataset,
  pruneBackups,
  resolveBackupKey,
  resolveScope,
  restoreToSandbox,
  runDrill,
} from "../backup/engine.js";
import {
  DEFAULT_RETENTION,
  describeRetention,
  type RetentionPolicy,
} from "../backup/retention.js";
import { createDumpBackup, realDumpDeps } from "../backup/dump.js";

/** Build a filesystem-safe, sortable backup id from scope + timestamp. */
function makeBackupId(
  kind: string,
  label: string | null,
  now: Date,
): string {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  const scopePart = label ? `-${label.replace(/[^a-zA-Z0-9_-]/g, "_")}` : "";
  return `${kind}${scopePart}-${stamp}`;
}

function parseAsOf(value: string | undefined): Date | null {
  if (value === undefined || value.trim() === "") return null;
  const ms = Date.parse(value.trim());
  if (Number.isNaN(ms)) {
    throw new CliError(`--as-of is not a valid timestamp: "${value}".`, {
      hint: 'Use an ISO 8601 instant, e.g. "2026-06-23T09:47:30Z".',
    });
  }
  return new Date(ms);
}

export type CreateBackupOptions = {
  tenant?: string;
  project?: string;
  full?: boolean;
  outDir?: string;
  offsiteDir?: string;
  keyFile?: string;
  requireEncryption?: boolean;
};

export async function runBackupCreate(
  client: pg.Client,
  conn: ConnectionOptions,
  opts: CreateBackupOptions,
  mode: OutputMode,
): Promise<void> {
  if (opts.project && !opts.tenant) {
    throw new CliError("--project requires --tenant (projects are tenant-scoped).");
  }
  const dir = opts.outDir ?? defaultBackupDir();
  const offsiteDir = opts.offsiteDir ?? defaultOffsiteDir();
  const key = await resolveBackupKey(opts.keyFile);
  if (key === null && opts.requireEncryption) {
    throw new CliError("Encryption is required but no key was provided.", {
      hint: "Pass --encrypt-key-file <path> or set APIOME_BACKUP_KEY (omit --require-encryption to allow plaintext).",
      exitCode: 2,
    });
  }

  const scope = opts.full
    ? await resolveScope(client, {})
    : await resolveScope(client, { tenant: opts.tenant, project: opts.project });
  const now = new Date();
  const label = scope.projectLabel ?? scope.tenantLabel;
  const id = makeBackupId(scope.kind, label, now);

  const manifest = await createBackupArtifacts(client, conn, {
    scope,
    id,
    dir,
    offsiteDir,
    key,
    createdAt: now.toISOString(),
  });

  if (!key) {
    note("WARNING: backup written UNENCRYPTED (no key provided). Do not store off-site as-is.");
  }
  if (mode.json) {
    printRecord(mode, { ...manifest, dir, offsiteDir: offsiteDir ?? null });
    return;
  }
  note(`Backup created: ${manifest.id}`);
  note(`  scope:      ${manifest.kind}${label ? ` (${label})` : ""}`);
  note(`  artifact:   ${manifest.artifact} (${manifest.sizeBytes} bytes${manifest.encrypted ? ", encrypted" : ""})`);
  note(`  recovery:   ${manifest.rpoMarker ?? "n/a"}`);
  note(`  written to: ${dir}${offsiteDir ? ` and off-site ${offsiteDir}` : ""}`);
}

export async function runBackupList(
  outDir: string | undefined,
  mode: OutputMode,
): Promise<void> {
  const dir = outDir ?? defaultBackupDir();
  const backups = await listBackups(dir);
  if (mode.json) {
    printRecord(mode, { dir, backups });
    return;
  }
  note(`Backups in ${dir}: ${backups.length}`);
  printRows(
    mode,
    backups.map((b) => ({
      id: b.id,
      kind: b.kind,
      scope: b.project ?? b.tenant ?? "—",
      createdAt: b.createdAt,
      sizeBytes: b.sizeBytes,
      enc: b.encrypted ? "yes" : "no",
      recovery: b.rpoMarker ?? "—",
    })),
    [
      { key: "id", label: "id" },
      { key: "kind", label: "kind" },
      { key: "scope", label: "scope" },
      { key: "createdAt", label: "created" },
      { key: "sizeBytes", label: "bytes" },
      { key: "enc", label: "enc" },
      { key: "recovery", label: "recovery-point" },
    ],
  );
}

export type RestoreOptions = {
  backupId: string;
  sandbox: string;
  asOf?: string;
  outDir?: string;
  keyFile?: string;
};

export async function runBackupRestore(
  client: pg.Client,
  opts: RestoreOptions,
  mode: OutputMode,
): Promise<void> {
  const dir = opts.outDir ?? defaultBackupDir();
  const backups = await listBackups(dir);
  const manifest = backups.find((b) => b.id === opts.backupId);
  if (!manifest) {
    throw new CliError(`No backup with id "${opts.backupId}" in ${dir}.`, {
      hint: "Run `apiome-db backup list` to see available backups.",
    });
  }
  const key = await resolveBackupKey(opts.keyFile);
  const dataset = await loadDataset(dir, manifest, key);
  const asOf = parseAsOf(opts.asOf);
  const result = await restoreToSandbox(client, opts.sandbox, dataset, asOf);

  if (mode.json) {
    printRecord(mode, result);
    return;
  }
  note(`Restored backup ${manifest.id} into sandbox schema "${result.sandboxSchema}".`);
  note(`  records restored: ${result.recordsRestored}`);
  note(`  deleted at point: ${result.deletedCount}`);
  note(`  events applied:   ${result.eventsApplied}`);
  note(`  recovery point:   ${result.asOf ?? "latest"}`);
  note(`Inspect with:  SELECT * FROM "${result.sandboxSchema}".pitr_records;`);
}

export type PruneOptions = {
  outDir?: string;
  keepDays?: number;
  keepLast?: number;
};

export async function runBackupPrune(opts: PruneOptions, mode: OutputMode): Promise<void> {
  const dir = opts.outDir ?? defaultBackupDir();
  const policy: RetentionPolicy = {
    keepDays: opts.keepDays ?? DEFAULT_RETENTION.keepDays,
    keepLast: opts.keepLast ?? DEFAULT_RETENTION.keepLast,
  };
  const result = await pruneBackups(dir, policy, new Date());
  if (mode.json) {
    printRecord(mode, { dir, policy, ...result });
    return;
  }
  note(`Retention (${describeRetention(policy)}) applied to ${dir}.`);
  if (result.pruned.length === 0) {
    note(`Nothing to prune; ${result.kept} backup(s) kept.`);
    return;
  }
  note(`Pruned ${result.pruned.length} backup(s); ${result.kept} kept:`);
  for (const id of result.pruned) note(`  ${id}`);
}

export type DrillOptions = {
  backupId?: string;
  outDir?: string;
  keyFile?: string;
  sandbox?: string;
  asOf?: string;
  rtoTargetMinutes?: number;
  rpoTargetMinutes?: number;
};

export async function runBackupDrill(
  client: pg.Client,
  opts: DrillOptions,
  mode: OutputMode,
): Promise<void> {
  const dir = opts.outDir ?? defaultBackupDir();
  const backups = await listBackups(dir);
  if (backups.length === 0) {
    throw new CliError(`No backups found in ${dir} to drill against.`, {
      hint: "Create one first: `apiome-db backup create --tenant <slug>`.",
    });
  }
  const manifest = opts.backupId
    ? backups.find((b) => b.id === opts.backupId)
    : backups.find((b) => b.kind !== "full") ?? backups[0];
  if (!manifest) {
    throw new CliError(`No backup with id "${String(opts.backupId)}" in ${dir}.`);
  }
  if (manifest.kind === "full") {
    throw new CliError("DR drills run against logical (tenant/project) backups, not full pg_dump archives.");
  }
  const key = await resolveBackupKey(opts.keyFile);
  const sandbox = opts.sandbox ?? `dr_drill_${manifest.id.replace(/[^a-z0-9_]/gi, "_").toLowerCase()}`.slice(0, 48);
  const startedAt = new Date();
  const result = await runDrill(client, {
    dir,
    manifest,
    key,
    sandboxSchema: sandbox,
    asOf: parseAsOf(opts.asOf),
    startedAt,
    now: new Date(),
    rtoTargetSeconds: opts.rtoTargetMinutes !== undefined ? opts.rtoTargetMinutes * 60 : undefined,
    rpoTargetSeconds: opts.rpoTargetMinutes !== undefined ? opts.rpoTargetMinutes * 60 : undefined,
  });

  if (mode.json) {
    printRecord(mode, result);
    if (result.summary.result === "fail") process.exitCode = 1;
    return;
  }
  note(`DR drill for backup ${result.backupId}:`);
  note(`  records restored: ${result.restore.recordsRestored}`);
  note(`  measured RTO:     ${result.summary.rtoLabel}`);
  note(`  recovery-point:   ${result.summary.rpoLabel ?? "n/a"}`);
  note(`  result:           ${result.summary.result.toUpperCase()}`);
  if (result.summary.result === "fail") {
    process.exitCode = 1;
    note("Drill FAILED: restored state did not verify.");
  }
}

export type DumpOptions = {
  outDir?: string;
  full?: boolean;
};

/**
 * `backup dump` — write a dated plain-SQL dump, or, when a prior-day backup exists, only the
 * unified diff from that prior state to the new dump.
 */
export async function runBackupDump(
  conn: ConnectionOptions,
  opts: DumpOptions,
  mode: OutputMode,
): Promise<void> {
  const dir = opts.outDir ?? defaultBackupDir();
  const result = await createDumpBackup(dir, realDumpDeps(conn), {
    now: new Date(),
    force: Boolean(opts.full),
  });

  if (mode.json) {
    printRecord(mode, { dir, ...result });
    return;
  }
  if (result.kind === "full") {
    note(`Full backup written: ${result.path} (${result.bytes} bytes).`);
  } else {
    note(`Incremental backup written: ${result.path} (${result.bytes} bytes).`);
    note(`  diff from prior day ${result.priorDate} → ${result.date}.`);
    note(`  restore: apply patches in date order onto the latest full (see README).`);
  }
}
