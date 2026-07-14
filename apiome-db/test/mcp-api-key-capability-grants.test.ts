/**
 * Structural assertions over the per-key MCP capability grants migration (#4767, MTG-1.3).
 *
 * V162 extends `apiome.mcp_api_keys` with `capability_mode` + `enabled_tools` jsonb,
 * CHECKs (mode vocab, array shape, inherit ⇒ empty list), and a write-time ceiling
 * ⊆ trigger. Runtime call gating and existing-tenant policy backfill remain later tickets.
 *
 * DB-free contract tests pin the migration shape.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V162__mcp_api_key_capability_grants_4767.sql";

let sql = "";
let lower = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
});

describe("MCP API key capability grants migration", () => {
  it("is present in scripts/ and ordered after V161", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V161__tenant_mcp_policies_4766.sql"),
    );
  });

  it("targets the apiome schema", () => {
    expect(lower).toContain("set search_path to apiome, public");
  });

  it("extends mcp_api_keys rather than creating mcp_api_key_tools", () => {
    expect(lower).toMatch(/alter table mcp_api_keys/);
    expect(lower).not.toMatch(/create table.*mcp_api_key_tools/);
  });

  it("documents rollback drops for up/down clean", () => {
    expect(lower).toContain(
      "drop trigger if exists trg_mcp_api_keys_capability_ceiling on apiome.mcp_api_keys",
    );
    expect(lower).toContain(
      "drop function if exists apiome.trg_mcp_api_keys_capability_ceiling()",
    );
    expect(lower).toContain(
      "drop function if exists apiome.mcp_enabled_tools_is_valid(jsonb)",
    );
    expect(lower).toContain("drop column if exists enabled_tools");
    expect(lower).toContain("drop column if exists capability_mode");
  });

  describe("columns and defaults", () => {
    it("adds capability_mode defaulting to inherit", () => {
      expect(lower).toMatch(
        /capability_mode\s+text not null default 'inherit'/,
      );
    });

    it("adds enabled_tools jsonb defaulting to empty array", () => {
      expect(lower).toMatch(
        /enabled_tools\s+jsonb not null default '\[\]'::jsonb/,
      );
    });

    it("constrains capability_mode to inherit | explicit", () => {
      expect(lower).toMatch(
        /mcp_api_keys_capability_mode_ck[\s\S]*?check \(capability_mode in \('inherit', 'explicit'\)\)/,
      );
    });

    it("requires inherit keys to store an empty enabled_tools list", () => {
      expect(lower).toMatch(
        /mcp_api_keys_inherit_empty_tools_ck[\s\S]*?check \(capability_mode <> 'inherit' or enabled_tools = '\[\]'::jsonb\)/,
      );
    });
  });

  describe("enabled_tools shape validation", () => {
    it("defines mcp_enabled_tools_is_valid for jsonb array of non-empty strings", () => {
      expect(lower).toMatch(
        /create or replace function apiome\.mcp_enabled_tools_is_valid\(p_tools jsonb\)/,
      );
      expect(lower).toContain("jsonb_typeof(p_tools) = 'array'");
      expect(lower).toContain("jsonb_array_elements_text(p_tools)");
      expect(lower).toContain("char_length(trim(tool_id)) = 0");
    });

    it("wires the helper into a CHECK on enabled_tools", () => {
      expect(lower).toMatch(
        /mcp_api_keys_enabled_tools_valid_ck[\s\S]*?check \(apiome\.mcp_enabled_tools_is_valid\(enabled_tools\)\)/,
      );
    });
  });

  describe("write-time ceiling ⊆ enforcement", () => {
    it("defines the BEFORE INSERT/UPDATE trigger function", () => {
      expect(lower).toMatch(
        /create or replace function apiome\.trg_mcp_api_keys_capability_ceiling\(\)/,
      );
      expect(lower).toContain("returns trigger");
      expect(lower).toContain("tenant_mcp_policies");
      expect(lower).toContain("tenant_mcp_policy_tools");
      expect(lower).toContain("in_ceiling");
    });

    it("attaches the trigger on capability columns and tenant_id", () => {
      expect(lower).toMatch(
        /create trigger trg_mcp_api_keys_capability_ceiling/,
      );
      expect(lower).toMatch(
        /before insert or update of capability_mode, enabled_tools, tenant_id/,
      );
      expect(lower).toContain(
        "execute function apiome.trg_mcp_api_keys_capability_ceiling()",
      );
    });

    it("documents full-ceiling semantics for unseeded / all|inherit_registry modes", () => {
      expect(sql).toMatch(/v_default_mode := 'all'/);
      expect(sql).toMatch(/default_mode = 'explicit'/);
      expect(sql).toMatch(/all \| inherit_registry/i);
    });
  });

  describe("orthogonality comments", () => {
    it("documents independence from scope_json and AGX agent keys", () => {
      expect(lower).toMatch(/comment on column mcp_api_keys\.capability_mode is/);
      expect(sql).toMatch(/scope_json/i);
      expect(sql).toMatch(/api_keys\.kind=agent/i);
    });

    it("documents that tenant default changes do not rewrite explicit keys", () => {
      expect(sql).toMatch(/does not rewrite explicit/i);
    });

    it("documents enable-set ⊆ tenant ceiling on enabled_tools", () => {
      expect(lower).toMatch(/comment on column mcp_api_keys\.enabled_tools is/);
      expect(sql).toMatch(/⊆ tenant ceiling|enable-set ⊆ tenant ceiling/i);
    });
  });
});
