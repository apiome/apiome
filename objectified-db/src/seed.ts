/**
 * Apply development seed data from seed/<env>/ (sample user, tenant, membership, license, API
 * key). Seeds are plain, idempotent SQL (`ON CONFLICT DO NOTHING`) applied in filename order
 * inside a single transaction. This is a DEV convenience: it is never wired into the Docker
 * entrypoint or compose, and the CLI refuses to run it under NODE_ENV=production without --force.
 */

import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type pg from "pg";

import { CliError } from "./errors.js";

/** Package root seed/<env> directory (parent of dist/ at runtime). Defaults to dev. */
export function defaultSeedDir(env = "dev"): string {
  const fromEnv = process.env.OBJECTIFIED_DB_SEED_DIR?.trim();
  if (fromEnv && fromEnv !== "") return fromEnv;
  const here = path.dirname(fileURLToPath(import.meta.url));
  return path.join(here, "..", "seed", env);
}

/** List `*.sql` seed files in a directory, sorted by filename (load order). */
export async function listSeedFiles(seedDir: string): Promise<string[]> {
  let entries: string[];
  try {
    entries = await fs.readdir(seedDir);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`Could not read seed directory ${seedDir}: ${message}`, { exitCode: 2 });
  }
  return entries.filter((f) => f.toLowerCase().endsWith(".sql")).sort();
}

export type SeedOptions = {
  seedDir: string;
  dryRun?: boolean;
};

export type SeedResult = {
  seedDir: string;
  applied: string[];
  dryRun: boolean;
};

/** Apply every seed file in `seedDir` (filename order) inside one transaction. */
export async function applySeeds(client: pg.Client, opts: SeedOptions): Promise<SeedResult> {
  const { seedDir, dryRun = false } = opts;
  const files = await listSeedFiles(seedDir);

  if (dryRun || files.length === 0) {
    return { seedDir, applied: files, dryRun };
  }

  await client.query("BEGIN");
  try {
    for (const file of files) {
      const sql = await fs.readFile(path.join(seedDir, file), "utf8");
      await client.query(sql);
    }
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    const message = err instanceof Error ? err.message : String(err);
    throw new CliError(`Failed applying seed data from ${seedDir}: ${message}`, { exitCode: 1 });
  }
  return { seedDir, applied: files, dryRun };
}
