/**
 * Structural assertions over the pacticipant owners migration (#6956, PFX-6.4).
 *
 * V450 lets a pacticipant have an owner team (CDG-2.2) and be reported in Unowned findings. DB-free
 * contract tests pin it:
 *
 *   1. It sets its own search path first.
 *   2. Both owner kind checks gain `pacticipant` and keep every V299 kind.
 *   3. It creates and drops no table, column or index.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V450__pacticipant_owners_6956.sql";

/** The owner kinds V299 left, every one of which must survive the swap. */
const V299_KINDS = [
  "project",
  "catalog_item",
  "mcp_endpoint",
  "consumer",
  "connector",
  "agent",
  "model",
  "gateway_config",
  "component",
];

/** Comments and `COMMENT ON` prose removed, whitespace collapsed, lowercased. */
function statementsOf(sql: string): string {
  return sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?';\n/g, "")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

/** The kinds listed by one named check constraint. */
function kindsOf(ddl: string, constraint: string): string[] {
  const match = new RegExp(`${constraint} check \\(entity_kind in \\(([^)]*)\\)\\)`).exec(ddl);
  if (!match) return [];
  return match[1].split(",").map((kind) => kind.trim().replace(/'/g, ""));
}

let ddl = "";

beforeAll(async () => {
  ddl = statementsOf(await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8"));
});

describe("pacticipant owners migration (PFX-6.4)", () => {
  it("is present in scripts/ and ordered after the contract-health migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(files.indexOf("V449__pact_health_window_6955.sql"));
  });

  it("sets its own search path before changing anything", () => {
    expect(ddl.trim().startsWith("set search_path to apiome, public")).toBe(true);
  });

  it.each(["entity_owners_kind_check", "unowned_findings_kind_check"])(
    "%s gains pacticipant and keeps every earlier kind",
    (constraint) => {
      const kinds = kindsOf(ddl, constraint);
      expect(kinds).toEqual([...V299_KINDS, "pacticipant"]);
    },
  );

  it("creates and drops no table, column or index", () => {
    expect(ddl).not.toContain("create table");
    expect(ddl).not.toContain("create index");
    expect(ddl).not.toContain("drop table");
    expect(ddl).not.toContain("drop column");
    expect(ddl).not.toContain("add column");
  });
});
