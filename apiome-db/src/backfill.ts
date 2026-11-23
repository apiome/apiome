/**
 * Resumable data backfills that run outside the migration transaction.
 *
 * A migration is one transaction, so a backfill inside it holds its locks until the last row is
 * done and starts over if it is interrupted. The backfills here are the other kind: the migration
 * adds a SQL function that does one bounded batch, and this module calls it in a loop, each call
 * its own transaction. Stopping at any point loses nothing — the next run continues with the rows
 * that are still pending — and readers are correct throughout, because they recompute a value
 * that is not stored yet.
 *
 * `apiome-db migrate` runs every backfill here after it has applied the migrations, so an upgrade
 * needs no extra step; `apiome-db backfill <name>` runs one on demand, and `--verify` checks it.
 *
 * Backfills:
 *
 * - **mcp-version-facts** (DBP-1.17, #7200; V425): the derived facts of MCP endpoint versions
 *   recorded before the fact columns existed. Batch function
 *   `apiome.backfill_mcp_version_facts(limit)`; verification
 *   `apiome.verify_mcp_version_facts(limit)`, which returns the snapshots whose stored facts
 *   differ from the recomputed ones.
 */

import type pg from "pg";

import { CliError } from "./errors.js";

/** Snapshots per batch unless the caller says otherwise. */
export const DEFAULT_BACKFILL_BATCH = 500;

/** Most mismatching snapshots `--verify` lists. */
export const VERIFY_SAMPLE_LIMIT = 20;

/** What one backfill run did. */
export type BackfillResult = {
  /** The backfill's name. */
  name: "mcp-version-facts";
  /** False when the database does not have the backfill's function (its migration is not applied). */
  available: boolean;
  /** Rows derived by this run. */
  derived: number;
  /** Batches this run executed (the last one, which finds nothing, is not counted). */
  batches: number;
};

/** What a verification found. */
export type VerifyResult = {
  name: "mcp-version-facts";
  available: boolean;
  /** Snapshots still without facts (the backfill has not reached them). */
  pending: number;
  /** Snapshots whose stored facts differ from the recomputed ones, up to {@link VERIFY_SAMPLE_LIMIT}. */
  mismatches: { version_id: string; stored: unknown; recomputed: unknown }[];
};

/** Whether a function with this signature exists (`to_regprocedure` is NULL when it does not). */
async function functionExists(client: pg.Client, signature: string): Promise<boolean> {
  const res = await client.query("SELECT to_regprocedure($1) IS NOT NULL AS present", [signature]);
  return Boolean(res.rows[0]?.present);
}

/**
 * Derive the facts of every MCP endpoint version that has none, one batch per transaction.
 *
 * @param client An open connection.
 * @param opts `batch`: snapshots per batch (a whole number ≥ 1, default
 *   {@link DEFAULT_BACKFILL_BATCH}). `onBatch`: called after each batch with the running total.
 * @returns How many snapshots were derived. `available` is false, and nothing is done, when V425
 *   is not applied to this database.
 * @throws CliError For a batch size that is not a whole number ≥ 1.
 */
export async function backfillMcpVersionFacts(
  client: pg.Client,
  opts: { batch?: number; onBatch?: (derived: number) => void } = {},
): Promise<BackfillResult> {
  const batch = opts.batch ?? DEFAULT_BACKFILL_BATCH;
  if (!Number.isInteger(batch) || batch < 1) {
    throw new CliError("--batch must be a whole number ≥ 1.", { exitCode: 2 });
  }
  const result: BackfillResult = { name: "mcp-version-facts", available: false, derived: 0, batches: 0 };
  if (!(await functionExists(client, "apiome.backfill_mcp_version_facts(integer)"))) return result;
  result.available = true;

  // Each statement is its own transaction (the client is in autocommit), so a batch that has
  // returned is durable whatever happens next.
  for (;;) {
    const res = await client.query("SELECT apiome.backfill_mcp_version_facts($1) AS derived", [batch]);
    const derived = Number(res.rows[0]?.derived ?? 0);
    if (!(derived > 0)) break;
    result.derived += derived;
    result.batches += 1;
    opts.onBatch?.(result.derived);
  }
  return result;
}

/**
 * Check the stored MCP endpoint version facts against the recomputed ones.
 *
 * @param client An open connection.
 * @returns The snapshots still pending and a sample of mismatching ones (none when all is well).
 */
export async function verifyMcpVersionFacts(client: pg.Client): Promise<VerifyResult> {
  const result: VerifyResult = { name: "mcp-version-facts", available: false, pending: 0, mismatches: [] };
  if (!(await functionExists(client, "apiome.verify_mcp_version_facts(integer)"))) return result;
  result.available = true;
  const pending = await client.query(
    "SELECT count(*)::int AS pending FROM apiome.mcp_endpoint_versions WHERE tool_count IS NULL",
  );
  result.pending = Number(pending.rows[0]?.pending ?? 0);
  const mismatches = await client.query(
    "SELECT version_id::text AS version_id, stored, recomputed FROM apiome.verify_mcp_version_facts($1)",
    [VERIFY_SAMPLE_LIMIT],
  );
  result.mismatches = mismatches.rows as VerifyResult["mismatches"];
  return result;
}

/**
 * Run every backfill, as `apiome-db migrate` does after applying migrations.
 *
 * @param client An open connection.
 * @returns One result per backfill.
 */
export async function runPendingBackfills(client: pg.Client): Promise<BackfillResult[]> {
  return [await backfillMcpVersionFacts(client)];
}
