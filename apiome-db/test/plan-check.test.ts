/**
 * Plan check (DBP-1.1, #7184). DB-free: plans are fixtures in the shape of
 * `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` output. The nightly job (apiome-db-scale.yml) runs the
 * real list on the scale database and proves a deliberately broken query fails it.
 */

import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { CliError } from "../src/errors.js";
import {
  type ExplainOutput,
  type HotQuery,
  defaultQueriesFile,
  judgePlan,
  loadPlanCheckSpec,
  planShape,
  relationsOf,
  reportMarkdown,
  resolveParam,
  validateSpec,
} from "../src/plan-check.js";
import { scaleId } from "../src/seed-scale.js";

const THRESHOLDS = { rowThreshold: 10_000, defaultBudgetMs: 50 };

/** An index-driven plan: Limit > Index Scan on classes. */
const INDEXED: ExplainOutput = {
  "Planning Time": 0.1,
  "Execution Time": 0.4,
  Plan: {
    "Node Type": "Limit",
    "Shared Hit Blocks": 12,
    "Shared Read Blocks": 0,
    Plans: [
      { "Node Type": "Index Scan", "Relation Name": "classes", Schema: "apiome", "Index Name": "idx_classes_version" },
    ],
  },
};

/** The broken shape: a cast on the key turns the lookup into a scan of every version. */
const SEQ_SCAN: ExplainOutput = {
  "Planning Time": 0.2,
  "Execution Time": 21.4,
  Plan: {
    "Node Type": "Hash Join",
    Plans: [
      { "Node Type": "Seq Scan", "Relation Name": "versions", Schema: "apiome" },
      {
        "Node Type": "Hash",
        Plans: [{ "Node Type": "Seq Scan", "Relation Name": "tenants", Schema: "apiome" }],
      },
    ],
  },
};

const ROWS = { "apiome.versions": 200_000, "apiome.tenants": 200, "apiome.classes": 1_000_000 };

const query = (extra: Partial<HotQuery> = {}): HotQuery => ({
  name: "q",
  source: "test",
  sql: "SELECT 1",
  ...extra,
});

describe("judgePlan", () => {
  it("passes an index-driven plan inside its budget", () => {
    const result = judgePlan(query(), INDEXED, ROWS, THRESHOLDS);
    expect(result.status).toBe("pass");
    expect(result.violations).toEqual([]);
    expect(result.shape).toBe("Limit > Index Scan on idx_classes_version");
    expect(result.sharedHitBlocks).toBe(12);
  });

  it("fails a sequential scan of a table above the row threshold, not of a small one", () => {
    const result = judgePlan(query(), SEQ_SCAN, ROWS, { ...THRESHOLDS, defaultBudgetMs: 1_000 });
    expect(result.status).toBe("fail");
    expect(result.seqScans).toEqual([
      { relation: "apiome.versions", estimatedRows: 200_000 },
      { relation: "apiome.tenants", estimatedRows: 200 },
    ]);
    expect(result.violations).toEqual(["sequential scan of apiome.versions (~200,000 rows > 10,000)"]);
  });

  it("fails a plan over its time budget", () => {
    const result = judgePlan(query({ budgetMs: 0.2 }), INDEXED, ROWS, THRESHOLDS);
    expect(result.status).toBe("fail");
    expect(result.violations).toEqual(["0.40 ms > budget 0.2 ms"]);
  });

  it("accepts a sequential scan the query declares as intended, and still applies the budget", () => {
    const allowSeqScan = [{ relation: "apiome.versions", reason: "stops at a LIMIT" }];
    const roomy = { ...THRESHOLDS, defaultBudgetMs: 1_000 };
    const result = judgePlan(query({ allowSeqScan }), SEQ_SCAN, ROWS, roomy);
    expect(result.status).toBe("pass");
    expect(result.violations).toEqual([]);
    expect(result.allowedSeqScans).toEqual(["sequential scan of apiome.versions by design: stops at a LIMIT"]);
    // The scan is still listed, and a slow plan still fails.
    expect(result.seqScans).toContainEqual({ relation: "apiome.versions", estimatedRows: 200_000 });
    expect(judgePlan(query({ allowSeqScan, budgetMs: 1 }), SEQ_SCAN, ROWS, THRESHOLDS).status).toBe("fail");
    // Allowing one relation does not allow another.
    const other = [{ relation: "apiome.classes", reason: "x" }];
    expect(judgePlan(query({ allowSeqScan: other }), SEQ_SCAN, ROWS, roomy).status).toBe("fail");
  });

  it("reports a known query's violations without failing, and flags it once it is fixed", () => {
    const known = { issue: "#7193", reason: "uuid cast" };
    expect(judgePlan(query({ known }), SEQ_SCAN, ROWS, THRESHOLDS).status).toBe("known");
    expect(judgePlan(query({ known }), INDEXED, ROWS, THRESHOLDS).status).toBe("fixed");
  });
});

describe("plan helpers", () => {
  it("lists each relation once", () => {
    expect(relationsOf(SEQ_SCAN)).toEqual(["apiome.versions", "apiome.tenants"]);
  });

  it("shortens a long plan outline", () => {
    expect(planShape(SEQ_SCAN, 2)).toBe("Hash Join > Seq Scan on versions > … (2 more)");
  });

  it("renders a Markdown row per query", () => {
    const report = {
      rowThreshold: 10_000,
      failed: 1,
      results: [judgePlan(query({ name: "broken" }), SEQ_SCAN, ROWS, THRESHOLDS)],
    };
    const md = reportMarkdown(report);
    expect(md).toContain("1 queries, 1 failed");
    expect(md).toContain("| broken | **FAIL** | 21.40 | 50 |");
    const allowSeqScan = [{ relation: "apiome.versions", reason: "stops at a LIMIT" }];
    const allowed = judgePlan(query({ name: "bounded", allowSeqScan }), SEQ_SCAN, ROWS, { ...THRESHOLDS, defaultBudgetMs: 1_000 });
    expect(reportMarkdown({ rowThreshold: 10_000, failed: 0, results: [allowed] })).toContain(
      "sequential scan of apiome.versions by design: stops at a LIMIT",
    );
  });
});

describe("resolveParam", () => {
  it("resolves seeded ids and id ranges", () => {
    expect(resolveParam("scale:version:0")).toBe(scaleId("version", 0));
    expect(resolveParam("scale-ids:version:0-2")).toEqual([0, 1, 2].map((i) => scaleId("version", i)));
  });

  it("passes other values through", () => {
    expect(resolveParam(50)).toBe(50);
    expect(resolveParam("Class1")).toBe("Class1");
  });

  it("rejects a reversed or huge range", () => {
    expect(() => resolveParam("scale-ids:version:5-1")).toThrow(CliError);
    expect(() => resolveParam("scale-ids:version:0-20000")).toThrow(CliError);
  });
});

describe("query lists", () => {
  it("rejects duplicate names, missing SQL and bad budgets", () => {
    const base = { ...THRESHOLDS, queries: [query()] };
    expect(() => validateSpec({ ...base, queries: [query(), query()] })).toThrow(/duplicate/);
    expect(() => validateSpec({ ...base, queries: [query({ sql: " " })] })).toThrow(/needs a name and sql/);
    expect(() => validateSpec({ ...base, queries: [query({ budgetMs: 0 })] })).toThrow(/budgetMs/);
    expect(() => validateSpec({ ...base, queries: [] })).toThrow(/non-empty/);
  });

  it("rejects malformed settings and seq-scan allowances", () => {
    const base = { ...THRESHOLDS, queries: [query()] };
    expect(() => validateSpec({ ...base, queries: [query({ settings: { jit: "off" } })] })).not.toThrow();
    expect(() => validateSpec({ ...base, queries: [query({ settings: { "jit; drop": "off" } })] })).toThrow(/settings/);
    expect(() =>
      validateSpec({ ...base, queries: [query({ settings: { jit: 0 as unknown as string } })] }),
    ).toThrow(/settings/);
    expect(() =>
      validateSpec({ ...base, queries: [query({ allowSeqScan: [{ relation: "apiome.versions", reason: "" }] })] }),
    ).toThrow(/allowSeqScan/);
  });

  it("reports an unreadable or malformed file", async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "plan-check-"));
    const bad = path.join(dir, "bad.json");
    await fs.writeFile(bad, "{");
    await expect(loadPlanCheckSpec(bad)).rejects.toThrow(/not JSON/);
    await expect(loadPlanCheckSpec(path.join(dir, "missing.json"))).rejects.toThrow(/Could not read/);
  });

  it("ships a valid hot-query list whose ids all resolve", async () => {
    const spec = await loadPlanCheckSpec(defaultQueriesFile());
    expect(spec.queries.length).toBeGreaterThanOrEqual(10);
    for (const q of spec.queries) {
      expect(q.source, q.name).toMatch(/\S/);
      for (const p of q.params ?? []) expect(() => resolveParam(p)).not.toThrow();
      // Placeholders and parameters agree.
      const highest = Math.max(0, ...[...q.sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])));
      expect(highest, q.name).toBe((q.params ?? []).length);
    }
  });

  it("ships a broken-query list that the check must fail", async () => {
    const file = path.join(path.dirname(defaultQueriesFile()), "broken-query.json");
    const spec = await loadPlanCheckSpec(file);
    expect(spec.queries).toHaveLength(1);
    expect(spec.queries[0]?.known).toBeUndefined();
  });
});
