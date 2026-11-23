import type pg from "pg";

import {
  applyPendingMigrations,
  cleanDatabase,
  cleanDisabled,
  defaultScriptsDir,
  getMigrationStatus,
  repairHistory,
} from "../migrate.js";
import { runPendingBackfills, type BackfillResult } from "../backfill.js";
import { applySeeds, defaultSeedDir } from "../seed.js";
import { applyScaleSeed, resolveScaleParams, type ScaleStepResult } from "../seed-scale.js";
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
  // Resumable backfills run after the migrations, one batch per transaction (src/backfill.ts).
  // They run on every migrate, not only when a migration was applied, so an interrupted backfill
  // is finished by the next run; with nothing pending each costs one index probe.
  const backfills: BackfillResult[] = result.dryRun ? [] : await runPendingBackfills(client);

  if (mode.json) {
    printRecord(mode, { scriptsDir, ...result, backfills });
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
  } else {
    note(`Applied ${result.applied.length} migration(s):`);
    for (const f of result.applied) note(`  ${f}`);
  }
  for (const backfill of backfills) {
    if (backfill.derived > 0) {
      note(`Backfill ${backfill.name}: ${backfill.derived} row(s) in ${backfill.batches} batch(es).`);
    }
  }
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
    "Drop the apiome schema and migration history (all data will be lost)?",
    Boolean(opts.yes),
  );
  if (!ok) {
    note("Aborted.");
    return;
  }

  const result = await cleanDatabase(client);
  printRecord(mode, { cleaned: true, ...result });
}

/** The seed profiles `apiome-db seed --profile` accepts. */
export const SEED_PROFILES = ["dev", "scale"] as const;
export type SeedProfile = (typeof SEED_PROFILES)[number];

export type SeedOptions = {
  seedDir?: string;
  dryRun?: boolean;
  force?: boolean;
  /** `dev` (default): the SQL fixtures in seed/dev/. `scale`: the generated large database. */
  profile?: string;
  /** `scale` only: multiplier for every row count (default 1, the audit volume). */
  scaleFactor?: number;
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

  const profile = opts.profile ?? "dev";
  if (!(SEED_PROFILES as readonly string[]).includes(profile)) {
    throw new CliError(`Unknown seed profile "${profile}".`, {
      exitCode: 2,
      hint: `Use one of: ${SEED_PROFILES.join(", ")}.`,
    });
  }
  if (profile === "scale") {
    if (opts.seedDir) {
      throw new CliError("--dir applies to the dev profile only.", { exitCode: 2 });
    }
    await runScaleSeed(client, opts, mode);
    return;
  }
  if (opts.scaleFactor !== undefined) {
    throw new CliError("--scale-factor applies to --profile scale only.", { exitCode: 2 });
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

/** `apiome-db seed --profile scale`: build the large benchmark database (DBP-1.1, #7184). */
async function runScaleSeed(client: pg.Client, opts: SeedOptions, mode: OutputMode): Promise<void> {
  const params = resolveScaleParams(opts.scaleFactor ?? 1);
  const progress = (step: ScaleStepResult): void => {
    if (mode.json) return;
    const what =
      step.status === "planned"
        ? `would insert up to ${step.rows.toLocaleString("en-US")} rows`
        : step.status === "skipped"
          ? "already complete"
          : `inserted ${step.inserted.toLocaleString("en-US")} rows in ${(step.ms / 1000).toFixed(1)} s`;
    note(`  ${step.name.padEnd(22)} ${what}`);
  };
  if (!mode.json) note(opts.dryRun ? "Dry run: scale profile steps:" : "Applying the scale seed profile:");
  const result = await applyScaleSeed(client, params, { dryRun: opts.dryRun, onStep: progress });
  if (mode.json) {
    printRecord(mode, result);
    return;
  }
  if (result.note) note(result.note);
  if (!result.dryRun) note(`Scale seed done in ${(result.totalMs / 1000).toFixed(1)} s.`);
}
