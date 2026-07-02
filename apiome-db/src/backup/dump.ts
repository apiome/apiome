/**
 * `backup dump` — daily plain-SQL dumps with day-over-day diffs.
 *
 * Each run takes a `pg_dump --format=plain` of the database and writes a dated file:
 *
 *   - `backup-YYYY-MM-DD.sql`        a FULL plain-SQL dump.
 *   - `backup-YYYY-MM-DD.sql.patch`  a unified DIFF from the most recent prior day's backup.
 *
 * The first backup (or any run forced with `--full`) is a full dump. When a prior-day backup
 * already exists, today's run instead stores only the unified diff from that prior state to the new
 * dump — the standard incremental scheme that keeps day-to-day storage small. Restoring a given day
 * means starting from the most recent full and applying each patch in date order (see README); the
 * patches are ordinary `diff -u` output, so the system `patch` tool restores them.
 *
 * To diff against the prior day we must reconstruct that day's full SQL. Reconstruction walks back
 * to the latest full on/before the prior day and replays the intervening patches — the same chain a
 * restore follows. The pg_dump / diff / patch steps are injected as `BackupDumpDeps` so the
 * orchestration is unit-tested without shelling out, while the real deps wrap pg_dump and GNU
 * diff/patch.
 */

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import type { ConnectionOptions } from "../db.js";
import { CliError } from "../errors.js";
import { runPgDump } from "./engine.js";

const execFileAsync = promisify(execFile);

const FULL_RE = /^backup-(\d{4}-\d{2}-\d{2})\.sql$/;
const PATCH_RE = /^backup-(\d{4}-\d{2}-\d{2})\.sql\.patch$/;

/** A backup file on disk, classified as a full dump or an incremental patch. */
export type BackupEntry = {
  /** Calendar date `YYYY-MM-DD`. */
  date: string;
  filename: string;
  kind: "full" | "patch";
};

/** Format a Date as a local-calendar `YYYY-MM-DD` (the day the backup is taken). */
export function formatDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Parse a backup filename into an entry, or null when it is not a backup file. */
export function parseBackupFilename(name: string): BackupEntry | null {
  const full = name.match(FULL_RE);
  if (full) return { date: full[1] as string, filename: name, kind: "full" };
  const patch = name.match(PATCH_RE);
  if (patch) return { date: patch[1] as string, filename: name, kind: "patch" };
  return null;
}

/** List backup entries in `dir`, sorted by date ascending. Missing dir → empty list. */
export async function listBackupEntries(dir: string): Promise<BackupEntry[]> {
  let names: string[];
  try {
    names = await fs.readdir(dir);
  } catch (err) {
    if ((err as { code?: string }).code === "ENOENT") return [];
    throw err;
  }
  const entries = names
    .map(parseBackupFilename)
    .filter((e): e is BackupEntry => e !== null)
    .sort((a, b) => a.date.localeCompare(b.date));
  return entries;
}

/**
 * Plan how to reconstruct the backup at `targetIndex`: the latest full at/before it, then every
 * patch from there up to and including the target. Throws when no full anchors the chain.
 */
export function planReconstruction(
  entries: BackupEntry[],
  targetIndex: number,
): { baseIndex: number; patchIndices: number[] } {
  if (targetIndex < 0 || targetIndex >= entries.length) {
    throw new CliError(`Reconstruction target out of range (${targetIndex}).`);
  }
  let baseIndex = -1;
  for (let i = targetIndex; i >= 0; i--) {
    if ((entries[i] as BackupEntry).kind === "full") {
      baseIndex = i;
      break;
    }
  }
  if (baseIndex === -1) {
    throw new CliError(
      `Cannot reconstruct ${(entries[targetIndex] as BackupEntry).filename}: no full backup precedes it.`,
      { hint: "The base full dump is missing; restore an earlier full or run a fresh full backup." },
    );
  }
  const patchIndices: number[] = [];
  for (let i = baseIndex + 1; i <= targetIndex; i++) patchIndices.push(i);
  return { baseIndex, patchIndices };
}

/** Injected effects: dump the DB, diff two SQL texts, and apply a patch. */
export type BackupDumpDeps = {
  /** Produce a plain-SQL dump of the database. */
  dump: () => Promise<string>;
  /** Unified diff transforming `oldText` into `newText` (i.e. `diff -u old new`). */
  diff: (oldText: string, newText: string) => Promise<string>;
  /** Apply `patchText` to `oldText`, returning the patched text. */
  applyPatch: (oldText: string, patchText: string) => Promise<string>;
};

/** Reconstruct the full SQL content of the entry at `targetIndex` by replaying its patch chain. */
export async function reconstructContent(
  dir: string,
  entries: BackupEntry[],
  targetIndex: number,
  deps: BackupDumpDeps,
): Promise<string> {
  const { baseIndex, patchIndices } = planReconstruction(entries, targetIndex);
  let content = await fs.readFile(path.join(dir, (entries[baseIndex] as BackupEntry).filename), "utf8");
  for (const idx of patchIndices) {
    const patch = await fs.readFile(path.join(dir, (entries[idx] as BackupEntry).filename), "utf8");
    content = await deps.applyPatch(content, patch);
  }
  return content;
}

export type BackupDumpResult = {
  /** Date of this backup. */
  date: string;
  /** Whether a full dump or an incremental patch was written. */
  kind: "full" | "patch";
  /** Absolute path of the file written. */
  path: string;
  /** Bytes written. */
  bytes: number;
  /** The prior-day backup diffed against (null for a full). */
  priorDate: string | null;
};

/**
 * Create today's backup in `dir`. Writes a full dump when no prior backup exists or `force` is set;
 * otherwise writes a unified diff from the most recent prior-day backup to the fresh dump. Re-running
 * on the same day replaces that day's existing file.
 */
export async function createDumpBackup(
  dir: string,
  deps: BackupDumpDeps,
  opts: { now: Date; force?: boolean },
): Promise<BackupDumpResult> {
  await fs.mkdir(dir, { recursive: true });
  const today = formatDate(opts.now);

  // Remove any existing backup for today so a re-run cleanly replaces it (full or patch).
  const existing = await listBackupEntries(dir);
  for (const e of existing.filter((x) => x.date === today)) {
    await fs.rm(path.join(dir, e.filename), { force: true });
  }
  const entries = existing.filter((x) => x.date !== today);

  // The prior backup is the most recent one strictly before today.
  const priorIndex = entries.length - 1;
  const prior = priorIndex >= 0 ? entries[priorIndex] : undefined;

  const newDump = await deps.dump();

  if (!prior || opts.force) {
    const filename = `backup-${today}.sql`;
    const filePath = path.join(dir, filename);
    await fs.writeFile(filePath, newDump);
    return { date: today, kind: "full", path: filePath, bytes: Buffer.byteLength(newDump), priorDate: null };
  }

  const priorContent = await reconstructContent(dir, entries, priorIndex, deps);
  const patch = await deps.diff(priorContent, newDump);
  const filename = `backup-${today}.sql.patch`;
  const filePath = path.join(dir, filename);
  await fs.writeFile(filePath, patch);
  return {
    date: today,
    kind: "patch",
    path: filePath,
    bytes: Buffer.byteLength(patch),
    priorDate: prior.date,
  };
}

// ───────────────────────── real (shell-backed) deps ─────────────────────────

/** Production deps: pg_dump for the dump, GNU diff/patch for the incremental steps. */
export function realDumpDeps(conn: ConnectionOptions): BackupDumpDeps {
  return {
    dump: async () => (await runPgDump(conn, "plain")).toString("utf8"),
    diff: runUnifiedDiff,
    applyPatch: applyUnifiedPatch,
  };
}

/** Run `diff -u old new` via temp files. Exit code 1 (differences found) is the normal case. */
export async function runUnifiedDiff(oldText: string, newText: string): Promise<string> {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "apiome-diff-"));
  const oldFile = path.join(tmp, "old.sql");
  const newFile = path.join(tmp, "new.sql");
  try {
    await fs.writeFile(oldFile, oldText);
    await fs.writeFile(newFile, newText);
    const { stdout } = await execFileAsync(
      "diff",
      ["-u", "--label", "a/backup.sql", "--label", "b/backup.sql", oldFile, newFile],
      { encoding: "utf8", maxBuffer: 1024 * 1024 * 1024 },
    );
    return stdout; // identical files → empty diff
  } catch (err) {
    const e = err as { code?: number | string; stdout?: string };
    if (e.code === 1) return e.stdout ?? ""; // differences found — expected
    if (e.code === "ENOENT") {
      throw new CliError("`diff` was not found on PATH.", {
        hint: "Install GNU diffutils to use incremental (diff) backups.",
        exitCode: 2,
      });
    }
    throw new CliError(`diff failed (exit ${String(e.code)}).`);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
}

/** Apply a unified patch to `oldText` via the system `patch` tool, returning the patched text. */
export async function applyUnifiedPatch(oldText: string, patchText: string): Promise<string> {
  if (patchText.trim() === "") return oldText; // empty diff → unchanged
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), "apiome-patch-"));
  const origFile = path.join(tmp, "orig.sql");
  const patchFile = path.join(tmp, "change.patch");
  const outFile = path.join(tmp, "out.sql");
  try {
    await fs.writeFile(origFile, oldText);
    await fs.writeFile(patchFile, patchText);
    await execFileAsync("patch", ["--output", outFile, origFile, patchFile], {
      encoding: "utf8",
      maxBuffer: 1024 * 1024 * 1024,
    });
    return await fs.readFile(outFile, "utf8");
  } catch (err) {
    const e = err as { code?: number | string; stderr?: string };
    if (e.code === "ENOENT") {
      throw new CliError("`patch` was not found on PATH.", {
        hint: "Install GNU patch to reconstruct incremental backups.",
        exitCode: 2,
      });
    }
    throw new CliError(`patch failed (exit ${String(e.code)})${e.stderr ? `: ${e.stderr.trim()}` : "."}`);
  } finally {
    await fs.rm(tmp, { recursive: true, force: true });
  }
}
