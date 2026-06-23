import type pg from "pg";

import {
  applyPendingMigrations,
  cleanDatabase,
  cleanDisabled,
  defaultScriptsDir,
  getMigrationStatus,
  repairHistory,
} from "../migrate.js";
import { applySeeds, defaultSeedDir } from "../seed.js";
import type { OutputMode } from "../output.js";
import { note, printRecord, printRows } from "../output.js";
import { CliError } from "../errors.js";
import { confirmDestructive } from "../util.js";

export type MigrateOptions = {
  scriptsDir?: string;
  dryRun?: boolean;
};

export async function runMigrateStatus(
  client: pg.Client,
  opts: MigrateOptions,
  mode: OutputMode,
): Promise<void> {
  const scriptsDir = opts.scriptsDir ?? defaultScriptsDir();
  const status = await getMigrationStatus(client, scriptsDir);

  if (mode.json) {
    printRecord(mode, status);
    return;
  }

  note(`Migrations directory: ${status.scriptsDir}`);
  note(`Applied: ${status.applied.length} · Pending: ${status.pending.length}`);

  if (status.pending.length > 0) {
    printRows(
      mode,
      status.pending.map((filename) => ({ filename })),
      [{ key: "filename", label: "filename" }],
    );
  }
  if (status.applied.length > 0 && status.pending.length === 0) {
    note("All scripts have been previously applied.");
  }
}

export async function runMigrateApply(
  client: pg.Client,
  opts: MigrateOptions,
  mode: OutputMode,
): Promise<void> {
  const scriptsDir = opts.scriptsDir ?? defaultScriptsDir();
  const result = await applyPendingMigrations(client, { scriptsDir, dryRun: opts.dryRun });

  if (mode.json) {
    printRecord(mode, { scriptsDir, ...result });
    return;
  }

  if (result.dryRun) {
    if (result.applied.length === 0) {
      note("Dry run: no pending migrations.");
    } else {
      note("Dry run: would apply:");
      for (const f of result.applied) note(`  ${f}`);
    }
    return;
  }

  if (result.applied.length === 0) {
    note("All scripts have been previously applied.");
    return;
  }

  note(`Applied ${result.applied.length} migration(s):`);
  for (const f of result.applied) note(`  ${f}`);
}

export async function runRepair(
  client: pg.Client,
  opts: MigrateOptions,
  mode: OutputMode,
): Promise<void> {
  const scriptsDir = opts.scriptsDir ?? defaultScriptsDir();
  const result = await repairHistory(client, scriptsDir);

  if (mode.json) {
    printRecord(mode, { scriptsDir, ...result });
    return;
  }

  if (result.realigned.length === 0 && result.removedFailed.length === 0) {
    note("Repair: history already consistent — nothing to do.");
    return;
  }
  if (result.realigned.length > 0) {
    note(`Realigned ${result.realigned.length} checksum(s):`);
    for (const f of result.realigned) note(`  ${f}`);
  }
  if (result.removedFailed.length > 0) {
    note(`Removed ${result.removedFailed.length} failed migration row(s).`);
  }
}

export type CleanOptions = {
  yes?: boolean;
  force?: boolean;
};

export async function runClean(
  client: pg.Client,
  opts: CleanOptions,
  mode: OutputMode,
): Promise<void> {
  if (process.env.NODE_ENV === "production" && !opts.force) {
    throw new CliError("Refusing to clean: NODE_ENV=production.", {
      hint: "Pass --force only if you are absolutely certain (this drops all data).",
    });
  }
  if (cleanDisabled() && !opts.force) {
    throw new CliError("Clean is disabled (FLYWAY_CLEAN_DISABLED is not 'false').", {
      hint: "Set FLYWAY_CLEAN_DISABLED=false (or pass --force) to allow dropping the schema.",
    });
  }

  const ok = await confirmDestructive(
    "Drop the odb schema and migration history (all data will be lost)?",
    Boolean(opts.yes),
  );
  if (!ok) {
    note("Aborted.");
    return;
  }

  const result = await cleanDatabase(client);
  printRecord(mode, { cleaned: true, ...result });
}

export type SeedOptions = {
  seedDir?: string;
  dryRun?: boolean;
  force?: boolean;
};

export async function runSeed(
  client: pg.Client,
  opts: SeedOptions,
  mode: OutputMode,
): Promise<void> {
  if (process.env.NODE_ENV === "production" && !opts.force) {
    throw new CliError("Refusing to load dev seed data: NODE_ENV=production.", {
      hint: "Seed data is for development only. Pass --force to override.",
    });
  }

  const seedDir = opts.seedDir ?? defaultSeedDir();
  const result = await applySeeds(client, { seedDir, dryRun: opts.dryRun });

  if (mode.json) {
    printRecord(mode, result);
    return;
  }

  if (result.applied.length === 0) {
    note(`No seed files found in ${result.seedDir}.`);
    return;
  }
  note(result.dryRun ? `Dry run: would apply from ${seedDir}:` : `Applied seed data from ${seedDir}:`);
  for (const f of result.applied) note(`  ${f}`);
}
