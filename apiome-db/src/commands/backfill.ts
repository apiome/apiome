/**
 * `apiome-db backfill mcp-version-facts [--batch <n>] [--verify]` (DBP-1.17, #7200).
 * See src/backfill.ts.
 */

import type pg from "pg";

import { backfillMcpVersionFacts, verifyMcpVersionFacts } from "../backfill.js";
import { CliError } from "../errors.js";
import { note, printRecord, type OutputMode } from "../output.js";

export type BackfillOptions = {
  /** Snapshots per batch. */
  batch?: number;
  /** Check the stored facts instead of deriving any. */
  verify?: boolean;
};

/**
 * Derive (or, with `verify`, check) the stored facts of MCP endpoint versions.
 *
 * @param client An open connection.
 * @param opts Command options.
 * @param mode Table or JSON output.
 * @throws CliError With exit code 1 when V425 is not applied, or when `--verify` finds a snapshot
 *   whose stored facts are wrong.
 */
export async function runMcpVersionFactsBackfill(
  client: pg.Client,
  opts: BackfillOptions,
  mode: OutputMode,
): Promise<void> {
  if (opts.verify) {
    const result = await verifyMcpVersionFacts(client);
    if (!result.available) throw notMigrated();
    if (mode.json) printRecord(mode, result);
    else {
      note(`Snapshots without facts yet: ${result.pending}`);
      note(`Snapshots whose stored facts differ from the recomputed ones: ${result.mismatches.length}`);
      for (const m of result.mismatches) {
        note(`  ${m.version_id}  stored ${JSON.stringify(m.stored)}  recomputed ${JSON.stringify(m.recomputed)}`);
      }
    }
    if (result.mismatches.length > 0) {
      throw new CliError(`${result.mismatches.length} MCP endpoint version(s) have wrong stored facts.`, {
        exitCode: 1,
        hint: "Report this: stored facts are write-once and should always match their items.",
      });
    }
    return;
  }

  const result = await backfillMcpVersionFacts(client, {
    batch: opts.batch,
    onBatch: mode.json ? undefined : (derived) => note(`  ${derived} snapshot(s) derived…`),
  });
  if (!result.available) throw notMigrated();
  if (mode.json) printRecord(mode, result);
  else if (result.derived === 0) note("Every MCP endpoint version already has its facts.");
  else note(`Derived the facts of ${result.derived} MCP endpoint version(s) in ${result.batches} batch(es).`);
}

/** The error for a database that does not have the backfill's functions. */
function notMigrated(): CliError {
  return new CliError("This database does not have the MCP version facts (migration V425).", {
    exitCode: 1,
    hint: "Run `apiome-db migrate` first.",
  });
}
