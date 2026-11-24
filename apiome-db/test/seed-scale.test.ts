/**
 * The `scale` seed profile (DBP-1.1, #7184). DB-free: the statements are generated in TypeScript,
 * so these tests pin their parameters, determinism and idempotency guards. The full profile was
 * run against PostgreSQL 18 for the PR (and runs nightly in apiome-db-scale.yml).
 */

import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { runSeed } from "../src/commands/migrate.js";
import { CliError } from "../src/errors.js";
import {
  DEFAULT_SCALE_PARAMS,
  buildScaleSteps,
  resolveScaleParams,
  scaleId,
  scaleIdSql,
} from "../src/seed-scale.js";

describe("resolveScaleParams", () => {
  it("defaults to the audit's volume", () => {
    const params = resolveScaleParams();
    expect(params).toEqual(DEFAULT_SCALE_PARAMS);
    expect(params.projects).toBe(20_000);
    expect(params.projects * params.versionsPerProject).toBe(200_000);
    expect(params.classes).toBe(1_000_000);
    expect(params.classProperties).toBe(3_100_000);
    expect(params.paths).toBe(600_000);
    expect(params.operations).toBe(1_200_000);
    expect(params.largeVersionClasses).toBe(20_000);
  });

  it("scales counts but not per-parent sizes", () => {
    const params = resolveScaleParams(0.01);
    expect(params.projects).toBe(200);
    expect(params.classes).toBe(10_000);
    expect(params.versionsPerProject).toBe(DEFAULT_SCALE_PARAMS.versionsPerProject);
    expect(params.mcpItemsPerVersion).toBe(DEFAULT_SCALE_PARAMS.mcpItemsPerVersion);
  });

  it("keeps the shape consistent at tiny factors", () => {
    const params = resolveScaleParams(0.00001);
    expect(params.users).toBeGreaterThanOrEqual(params.tenants);
    expect(params.largeTenantProjects).toBeLessThanOrEqual(params.projects);
    expect(params.largeVersionClasses).toBeLessThanOrEqual(params.classes);
    expect(params.operations).toBeLessThanOrEqual(params.paths * 5);
    for (const value of Object.values(params)) expect(value).toBeGreaterThanOrEqual(1);
  });

  it("applies overrides after scaling", () => {
    expect(resolveScaleParams(0.5, { tenants: 7 }).tenants).toBe(7);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])("rejects scale factor %s", (factor) => {
    expect(() => resolveScaleParams(factor)).toThrow(CliError);
  });

  it("rejects a non-integer override", () => {
    expect(() => resolveScaleParams(1, { classes: 1.5 })).toThrow(/whole number/);
  });
});

describe("scaleId", () => {
  it("is the uuid form of md5('apiome-scale:<kind>:<n>'), as PostgreSQL casts it", () => {
    const hex = createHash("md5").update("apiome-scale:project:42").digest("hex");
    expect(scaleId("project", 42).replaceAll("-", "")).toBe(hex);
    expect(scaleId("project", 42)).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });

  it("matches the SQL expression's input text", () => {
    expect(scaleIdSql("class", "n")).toBe("md5('apiome-scale:class:' || (n))::uuid");
  });
});

describe("buildScaleSteps", () => {
  const steps = buildScaleSteps(resolveScaleParams());

  it("fills every table the ticket names, parents before children", () => {
    const names = steps.map((s) => s.name);
    expect(names).toEqual([
      "tenants",
      "users",
      "tenant_users",
      "tenant_administrators",
      "projects",
      "versions",
      "properties",
      "classes",
      "class_properties",
      "paths",
      "operations",
      "mcp_endpoints",
      "mcp_endpoint_versions",
      "mcp_capability_items",
      "usage_sources",
      "usage_daily",
      "workflow_audit",
      "access_audit",
      "version_content_counts",
      "version_publish_counts",
      "mcp_version_facts",
      "browse_public_projects",
    ]);
  });

  it("is deterministic: the same parameters give the same SQL", () => {
    expect(buildScaleSteps(resolveScaleParams())).toEqual(steps);
  });

  it("makes every statement idempotent and set-based", () => {
    for (const s of steps.filter((step) => !step.doneSql)) {
      expect(s.sql, s.name).toMatch(/^INSERT INTO apiome\.\w+/);
      expect(s.sql, s.name).toContain("generate_series(0, ");
      expect(s.sql, s.name).toMatch(/ON CONFLICT DO NOTHING$/);
      expect(s.sql, s.name).not.toMatch(/random\(|now\(\)|clock_timestamp|gen_random_uuid|uuid_generate/);
    }
  });

  it("fills the publish counts of existing revisions with an idempotent UPDATE (DBP-1.16)", () => {
    const counts = steps.find((s) => s.name === "version_publish_counts");
    expect(counts?.table).toBe("apiome.versions");
    // 9 of every project's 10 revisions are published.
    expect(counts?.rows).toBe(180_000);
    expect(counts?.sql).toMatch(/^UPDATE apiome\.versions v/);
    expect(counts?.sql).toContain("SET operation_count = COALESCE(o.operation_count, 0)");
    expect(counts?.sql).toContain("schema_count = COALESCE(s.schema_count, 0)");
    // Only rows that still lack a count are written, so a re-run changes nothing…
    expect(counts?.sql).toContain("AND (v.operation_count IS NULL OR v.schema_count IS NULL)");
    // …and the step is recognized as complete by its own check, not by a last row.
    expect(counts?.doneSql).toContain("operation_count IS NULL OR schema_count IS NULL");
    expect(counts?.bypassTriggers).toBe(true);
    expect(counts?.sql).not.toMatch(/random\(|now\(\)|clock_timestamp/);
  });

  it("refreshes the public-catalog summary with the migration's function, after the counts (DBP-1.27)", () => {
    const summary = steps.find((s) => s.name === "browse_public_projects");
    expect(summary?.table).toBe("apiome.browse_public_projects");
    // A quarter of the 20,000 projects publish public revisions.
    expect(summary?.rows).toBe(5_000);
    expect(summary?.sql).toBe(
      "SELECT apiome.refresh_browse_public_projects(ARRAY(SELECT id FROM apiome.projects))",
    );
    // Done when every row carries its latest revision's stored counts — not by a last row.
    expect(summary?.doneSql).toContain("v.operation_count IS DISTINCT FROM b.operation_count");
    expect(summary?.bypassTriggers).toBe(false);
    const names = steps.map((s) => s.name);
    expect(names.indexOf("browse_public_projects")).toBeGreaterThan(names.indexOf("version_publish_counts"));
  });

  it("derives the MCP endpoint version facts with the migration's backfill function (DBP-1.17)", () => {
    const facts = steps.find((s) => s.name === "mcp_version_facts");
    expect(facts?.table).toBe("apiome.mcp_endpoint_versions");
    // 2,000 endpoints with 5 snapshots each.
    expect(facts?.rows).toBe(10_000);
    expect(facts?.sql).toBe("SELECT apiome.backfill_mcp_version_facts(10000)");
    expect(facts?.doneSql).toContain("FROM apiome.mcp_endpoint_versions WHERE tool_count IS NULL");
    // The write-once guard must fire: it is what allows this update and nothing else.
    expect(facts?.bypassTriggers).toBe(false);
  });

  it("names each step's last row so a complete step can be skipped", () => {
    const byName = Object.fromEntries(steps.map((s) => [s.name, s]));
    expect(byName.classes?.lastId).toBe("class:999999");
    expect(byName.versions?.lastId).toBe("version:199999");
    expect(byName.class_properties?.rows).toBe(3_100_000);
    // usage_daily has no id column; it is checked by row count.
    expect(byName.usage_daily?.lastId).toBe("");
    // Home's count rollup (DBP-1.15) is keyed by version id.
    expect(byName.version_content_counts?.lastId).toBe("version:199999");
    expect(byName.version_content_counts?.keyColumn).toBe("version_id");
  });

  it("puts the skewed rows where the ticket asks", () => {
    const sql = Object.fromEntries(steps.map((s) => [s.name, s.sql]));
    // 5,000 projects in tenant 0, the large tenant.
    expect(sql.projects).toContain("CASE WHEN n < 5000 THEN 0 ELSE 1 + ((n) - 5000) % 199 END");
    expect(sql.tenants).toContain("'scale-large'");
    // The first 20,000 classes sit in version 0.
    expect(sql.classes).toContain("CASE WHEN n < 20000 THEN 0 ELSE 1 + (n - 20000) % 199999 END");
  });

  it("gives seeded users a password that is not a bcrypt hash", () => {
    const users = steps.find((s) => s.name === "users")?.sql ?? "";
    expect(users).toContain("'scale-seed-no-login'");
    expect(users).not.toMatch(/\$2[aby]\$/);
  });

  it("keeps usage buckets the size usage_buckets_valid() requires (11 bounds + 1)", () => {
    const usage = steps.find((s) => s.name === "usage_daily")?.sql ?? "";
    const buckets = usage.match(/ARRAY\[([0-9,]+)\]::bigint\[\]/)?.[1]?.split(",") ?? [];
    expect(buckets).toHaveLength(12);
    expect(buckets.map(Number).reduce((a, b) => a + b, 0)).toBe(10);
  });
});

describe("runSeed --profile", () => {
  const client = {} as never;
  const mode = { json: true };

  it("rejects an unknown profile", async () => {
    await expect(runSeed(client, { profile: "huge" }, mode)).rejects.toThrow(/Unknown seed profile/);
  });

  it("rejects --dir with the scale profile and --scale-factor with dev", async () => {
    await expect(runSeed(client, { profile: "scale", seedDir: "/tmp" }, mode)).rejects.toThrow(/--dir/);
    await expect(runSeed(client, { profile: "dev", scaleFactor: 2 }, mode)).rejects.toThrow(/--scale-factor/);
  });
});
