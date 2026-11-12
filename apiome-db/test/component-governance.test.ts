/**
 * Structural assertions over the component governance migration
 * (DCW-3.4, private-suite#2364).
 *
 * The migration adds the component-library policy to the governing style guide,
 * stage-bound approval decisions, and scheduled deprecations, without touching
 * the DCW-3.1 immutability and tenant-isolation guarantees. These tests verify
 * the DDL contract without a live database.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { describe, expect, it, beforeAll } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V367__component_governance_2364.sql";

let sql = "";

beforeAll(async () => {
  sql = (await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8")).toLowerCase();
});

describe("component governance migration", () => {
  it("is present in scripts/ and ordered after the V366 component library", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V366__operational_components_2353.sql"),
    );
  });

  it("puts the policy on the governing style guide (the existing governance primitive)", () => {
    expect(sql).toMatch(
      /alter table apiome\.style_guides\s+add column if not exists component_approval_stages jsonb not null default '\[\]'::jsonb/,
    );
    expect(sql).toMatch(
      /alter table apiome\.style_guides\s+add column if not exists component_deprecation_notice_days integer not null default 0/,
    );
    expect(sql).toContain("jsonb_array_length(component_approval_stages) <= 5");
    expect(sql).toContain("component_deprecation_notice_days between 0 and 365");
  });

  it("guards the constraints so a re-run is a no-op", () => {
    expect(sql).toContain("style_guides_component_approval_stages_ck");
    expect(sql).toContain("style_guides_component_deprecation_notice_days_ck");
    expect(sql.match(/if not exists \(\s*select 1\s+from pg_constraint/g)?.length).toBe(2);
  });

  it("creates the two governance tables, tenant-scoped with cascading FKs", () => {
    for (const table of ["component_revision_approvals", "component_revision_deprecations"]) {
      expect(sql).toMatch(new RegExp(`create table if not exists apiome\\.${table}`));
    }
    const matches = sql.match(
      /tenant_id uuid not null references apiome\.tenants\(id\) on delete cascade/g,
    );
    expect(matches?.length).toBe(2);
    expect(sql).not.toMatch(/create schema/);
  });

  it("reuses the COL-2.1 decision vocabulary and binds decisions to the payload digest", () => {
    expect(sql).toContain("decision in ('approve', 'request_changes')");
    expect(sql).toMatch(
      /unique \(revision_id, stage_index, user_id, payload_digest\)/,
    );
    expect(sql).toContain("stage_index between 0 and 4");
  });

  it("never modifies revision rows: deprecations reference revisions with RESTRICT", () => {
    expect(sql).not.toMatch(/alter table apiome\.operational_component_revisions/);
    expect(sql).not.toMatch(/update apiome\.operational_component_revisions/);
    expect(
      sql.match(/references apiome\.operational_component_revisions\(id\) on delete restrict/g)
        ?.length,
    ).toBe(2);
  });

  it("allows one live deprecation per revision and records cancellation", () => {
    expect(sql).toMatch(
      /create unique index if not exists uq_component_revision_deprecation_live\s+on apiome\.component_revision_deprecations \(revision_id\)\s+where cancelled_at is null/,
    );
    expect(sql).toContain("replacement_revision_id is null or replacement_revision_id <> revision_id");
  });

  it("documents the new audit actions on the ledger", () => {
    for (const action of [
      "revision.approval",
      "deprecation.schedule",
      "deprecation.cancel",
      "pin.upgrade",
      "upgrade.bulk",
    ]) {
      expect(sql).toContain(action);
    }
  });
});
