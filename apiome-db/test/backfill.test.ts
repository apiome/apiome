/**
 * The resumable backfill runner (DBP-1.17, #7200): batches until nothing is pending, reports what
 * it did, and stays out of the way on a database that does not have the backfill's functions.
 */

import type pg from "pg";
import { describe, expect, it } from "vitest";

import {
  DEFAULT_BACKFILL_BATCH,
  VERIFY_SAMPLE_LIMIT,
  backfillMcpVersionFacts,
  runPendingBackfills,
  verifyMcpVersionFacts,
} from "../src/backfill.js";
import { runMcpVersionFactsBackfill } from "../src/commands/backfill.js";
import { CliError } from "../src/errors.js";

type Call = { sql: string; params: unknown[] };

/**
 * A stand-in for a database with `pending` snapshots to derive.
 *
 * @param opts `present`: whether V425's functions exist. `pending`: snapshots without facts.
 *   `mismatches`: rows `verify_mcp_version_facts` returns.
 */
function fakeClient(opts: { present?: boolean; pending?: number; mismatches?: unknown[] } = {}) {
  const calls: Call[] = [];
  let pending = opts.pending ?? 0;
  const client = {
    query: async (sql: string, params: unknown[] = []) => {
      calls.push({ sql, params });
      if (sql.includes("to_regprocedure")) return { rows: [{ present: opts.present ?? true }] };
      if (sql.includes("backfill_mcp_version_facts")) {
        const derived = Math.min(pending, Number(params[0]));
        pending -= derived;
        return { rows: [{ derived }] };
      }
      if (sql.includes("count(*)")) return { rows: [{ pending }] };
      if (sql.includes("verify_mcp_version_facts")) return { rows: opts.mismatches ?? [] };
      throw new Error(`unexpected statement: ${sql}`);
    },
  };
  return { client: client as unknown as pg.Client, calls, pending: () => pending };
}

const batches = (calls: Call[]) => calls.filter((c) => c.sql.includes("backfill_mcp_version_facts"));

describe("backfillMcpVersionFacts", () => {
  it("derives batch after batch until none is pending, one statement per batch", async () => {
    const db = fakeClient({ pending: 1_250 });
    const seen: number[] = [];
    const result = await backfillMcpVersionFacts(db.client, { onBatch: (n) => seen.push(n) });
    expect(result).toEqual({ name: "mcp-version-facts", available: true, derived: 1_250, batches: 3 });
    expect(seen).toEqual([500, 1_000, 1_250]);
    // Three batches that did work, and the one that found nothing left.
    expect(batches(db.calls)).toHaveLength(4);
    expect(batches(db.calls).every((c) => c.params[0] === DEFAULT_BACKFILL_BATCH)).toBe(true);
    expect(db.pending()).toBe(0);
  });

  it("uses the batch size it is given", async () => {
    const db = fakeClient({ pending: 7 });
    const result = await backfillMcpVersionFacts(db.client, { batch: 2 });
    expect(result.derived).toBe(7);
    expect(result.batches).toBe(4);
  });

  it("does one probe when nothing is pending", async () => {
    const db = fakeClient({ pending: 0 });
    expect(await backfillMcpVersionFacts(db.client)).toMatchObject({ available: true, derived: 0, batches: 0 });
    expect(batches(db.calls)).toHaveLength(1);
  });

  it("continues where an interrupted run stopped", async () => {
    const db = fakeClient({ pending: 900 });
    // The first run is cut off after its first batch…
    await expect(
      backfillMcpVersionFacts(db.client, {
        onBatch: () => {
          throw new Error("killed");
        },
      }),
    ).rejects.toThrow("killed");
    expect(db.pending()).toBe(400);
    // …and the next one derives exactly what was left.
    expect((await backfillMcpVersionFacts(db.client)).derived).toBe(400);
  });

  it("does nothing on a database without the function", async () => {
    const db = fakeClient({ present: false, pending: 50 });
    expect(await backfillMcpVersionFacts(db.client)).toEqual({
      name: "mcp-version-facts",
      available: false,
      derived: 0,
      batches: 0,
    });
    expect(batches(db.calls)).toHaveLength(0);
  });

  it("rejects a batch size that is not a whole number ≥ 1", async () => {
    for (const batch of [0, -5, 2.5, Number.NaN]) {
      await expect(backfillMcpVersionFacts(fakeClient().client, { batch })).rejects.toBeInstanceOf(CliError);
    }
  });
});

describe("runPendingBackfills", () => {
  it("runs the MCP version facts backfill", async () => {
    const db = fakeClient({ pending: 3 });
    expect(await runPendingBackfills(db.client)).toEqual([
      { name: "mcp-version-facts", available: true, derived: 3, batches: 1 },
    ]);
  });
});

describe("verifyMcpVersionFacts", () => {
  it("reports what is pending and a bounded sample of mismatches", async () => {
    const mismatch = { version_id: "v1", stored: { tool_count: 7 }, recomputed: { tool_count: 0 } };
    const db = fakeClient({ pending: 4, mismatches: [mismatch] });
    expect(await verifyMcpVersionFacts(db.client)).toEqual({
      name: "mcp-version-facts",
      available: true,
      pending: 4,
      mismatches: [mismatch],
    });
    expect(db.calls.find((c) => c.sql.includes("verify_mcp_version_facts"))?.params).toEqual([VERIFY_SAMPLE_LIMIT]);
  });

  it("is unavailable before the migration", async () => {
    expect((await verifyMcpVersionFacts(fakeClient({ present: false }).client)).available).toBe(false);
  });
});

describe("backfill mcp-version-facts command", () => {
  const json = { json: true };

  it("fails with a hint when the migration is not applied", async () => {
    for (const verify of [false, true]) {
      await expect(
        runMcpVersionFactsBackfill(fakeClient({ present: false }).client, { verify }, json),
      ).rejects.toMatchObject({ exitCode: 1, hint: "Run `apiome-db migrate` first." });
    }
  });

  it("passes when verification finds nothing and fails when a stored fact is wrong", async () => {
    await expect(runMcpVersionFactsBackfill(fakeClient().client, { verify: true }, json)).resolves.toBeUndefined();
    const wrong = fakeClient({ mismatches: [{ version_id: "v1", stored: {}, recomputed: {} }] });
    await expect(runMcpVersionFactsBackfill(wrong.client, { verify: true }, json)).rejects.toMatchObject({
      exitCode: 1,
    });
  });

  it("verification derives nothing", async () => {
    const db = fakeClient({ pending: 9 });
    await runMcpVersionFactsBackfill(db.client, { verify: true }, json);
    expect(db.pending()).toBe(9);
  });
});
