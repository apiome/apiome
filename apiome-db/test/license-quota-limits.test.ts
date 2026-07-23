/**
 * Structural assertions over the license quota-limits migration (#64).
 *
 * V195 populates the three quota keys #64 asks the license to carry —
 * `max_projects`, `max_versions`, `max_ai_requests` — on the seeded Free/Paid/Sponsor
 * tiers, so each plan differentiates what it grants (before this, the tiers carried no
 * quota keys and every plan fell back to the Free defaults). It also documents the
 * canonical `seats` key set.
 *
 * These are DB-free contract tests pinning the migration's shape: that it seeds all
 * three tiers, uses the non-destructive fill-if-absent merge, introduces the AI key,
 * and stays storage-only (no enforcement DDL). They guard the "each plan encodes its
 * own project/version/AI limits" guarantee the apiome-ui enforcement path and the
 * apiome-rest license surface both read.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V195__license_quota_limits_64.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("license quota-limits migration", () => {
  it("is present and ordered after the V097 catalog it seeds into", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V097__license_catalog_feature_flags_and_user_t.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("seeds every quota key onto all three catalog tiers", () => {
    for (const tier of ["free", "paid", "sponsor"]) {
      expect(lower).toContain(`name = '${tier}' and license_type = '${tier}'`);
    }
    for (const key of ["max_projects", "max_versions", "max_ai_requests"]) {
      // Each key appears in every tier's jsonb_build_object plus the column comment.
      const hits = (lower.match(new RegExp(key, "g")) || []).length;
      expect(hits).toBeGreaterThanOrEqual(4);
    }
  });

  it("introduces the previously-absent AI functionality cap", () => {
    expect(lower).toContain("max_ai_requests");
  });

  it("uses the non-destructive fill-if-absent merge (built object || seats)", () => {
    // `jsonb_build_object(...) || seats` — existing operator-set keys win on the right,
    // so a customised limit is never clobbered.
    expect(lower).toMatch(/jsonb_build_object\([^)]*\)\s*\|\|\s*seats/s);
    // The reverse order (`seats || jsonb_build_object`) would overwrite operator edits.
    expect(lower).not.toMatch(/seats\s*\|\|\s*jsonb_build_object/);
  });

  it("grants Sponsor unlimited quotas via the negative sentinel", () => {
    expect(lower).toMatch(/'max_projects',\s*-1/);
    expect(lower).toMatch(/'max_ai_requests',\s*-1/);
  });

  it("bumps updated_at so the change is observable", () => {
    expect(lower).toContain("updated_at = current_timestamp");
  });

  it("documents the full canonical seats key set on the column", () => {
    expect(lower).toContain("comment on column apiome.licenses.seats");
    for (const key of ["max_projects", "max_versions", "max_ai_requests"]) {
      expect(lower).toContain(key);
    }
    expect(lower).toContain("negative value means unlimited");
  });

  it("is storage-only — no enforcement DDL (triggers/functions)", () => {
    // #64 stores the limits; enforcement is a follow-on, mirroring how V097 seat
    // storage preceded OLO-5.3 seat enforcement.
    expect(lower).not.toContain("create function");
    expect(lower).not.toContain("create or replace function");
    expect(lower).not.toContain("create trigger");
  });
});
