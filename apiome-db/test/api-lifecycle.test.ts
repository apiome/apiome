/**
 * Structural assertions over the product and plan lifecycle migration (APX-1.4, #6101).
 *
 * V389 adds deprecation and retirement dates, a message and a successor plan to `api_plans`, and the
 * same dates and message to `api_products`. DB-free contract tests pin the shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V389__api_lifecycle_apx_1_4.sql";

let lower = "";

beforeAll(async () => {
  lower = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("Product and plan lifecycle migration (APX-1.4)", () => {
  it("is present in scripts/ and ordered after V388", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V388__api_plans_apx_1_2.sql"));
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("adds the lifecycle columns to plans and products", () => {
    for (const column of ["deprecated_at", "retire_at", "retired_at", "deprecation_message"]) {
      expect(lower.match(new RegExp(`add column if not exists ${column} `, "g"))?.length).toBe(2);
    }
    expect(lower).toContain(
      "add column if not exists successor_plan_id uuid references api_plans(id) on delete set null",
    );
    expect(lower).toContain("add column if not exists owners_notified_at timestamp with time zone");
  });

  it("ties the dates to the state", () => {
    expect(lower).toContain("check (retire_at is null or state in ('deprecated', 'retired'))");
    expect(lower).toContain("check (retired_at is null or state = 'retired')");
  });

  it("keeps a plan from succeeding itself and bounds the message", () => {
    expect(lower).toContain("check (successor_plan_id is null or successor_plan_id <> id)");
    expect(lower).toContain("check (deprecation_message is null or length(deprecation_message) <= 1000)");
  });

  it("indexes the sunset timeline read", () => {
    expect(lower).toMatch(/idx_api_plans_retire_at\s+on api_plans \(tenant_id, retire_at\)/);
    expect(lower).toMatch(/idx_api_products_retire_at\s+on api_products \(tenant_id, retire_at\)/);
  });

  it("documents rollback and the issue", () => {
    expect(lower).toContain("rollback notes");
    expect(lower).toContain("apx-1.4 (#6101)");
  });
});
