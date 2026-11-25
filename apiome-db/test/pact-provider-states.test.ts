/**
 * Structural assertions over the provider-state registry migration (#6933, PFX-3.3).
 *
 * V441 adds `pact_provider_state` (one state of one provider and how it is set up) and
 * `pact_provider_state_override` (a different setup on one verification target). The rules the
 * database keeps: a name is unique per provider, setup kinds are a closed list, and every reference
 * carries the tenant so nothing crosses one.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V441__pact_provider_states_6933.sql";

/** Comments removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("provider-state registry (PFX-3.3)", () => {
  it("is ordered after the comparison-list migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V440__bidirectional_comparison_list_6929.sql"));
  });

  it("sets its own search_path and creates both tables idempotently", () => {
    expect(ddl.startsWith("set search_path to apiome, public;")).toBe(true);
    expect(ddl).toContain("create table if not exists pact_provider_state (");
    expect(ddl).toContain("create table if not exists pact_provider_state_override (");
  });

  it("keeps a state name unique per provider", () => {
    expect(ddl).toContain("constraint pact_provider_state_name_key unique (tenant_id, provider_id, name)");
  });

  it("closes the list of setup kinds on both tables", () => {
    const check = "setup->>'kind' in ('state_change', 'fixture')";
    expect(ddl.split(check).length - 1).toBe(2);
  });

  it("references provider, state and target with the tenant", () => {
    expect(ddl).toContain("foreign key (provider_id, tenant_id) references pacticipant (id, tenant_id) on delete cascade");
    expect(ddl).toContain(
      "foreign key (state_id, tenant_id) references pact_provider_state (id, tenant_id) on delete cascade",
    );
    expect(ddl).toContain(
      "foreign key (target_id, tenant_id) references verification_target (id, tenant_id) on delete cascade",
    );
  });

  it("allows one override per state and target", () => {
    expect(ddl).toContain("constraint pact_provider_state_override_key unique (state_id, target_id)");
  });
});
