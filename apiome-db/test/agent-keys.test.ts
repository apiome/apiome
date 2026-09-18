/**
 * Structural assertions over the agent key migration (#4537, AGX-3.1).
 *
 * V269 extends `apiome.api_keys` rather than adding a table: `kind` (`workspace` | `agent`),
 * `toolset_id` and `tool_allowlist`, reusing the V006 `expires_at`, hashing and soft-delete
 * revocation. DB-free contract tests pin the rules the ticket's acceptance criteria turn into
 * schema rules:
 *
 *   1. **The two kinds are exclusive.** An agent key has a toolset and an allowlist; a workspace
 *      key has neither.
 *   2. **An agent key is not a REST credential.** It carries exactly the `agent:invoke` scope,
 *      which no REST route allowlists, and a workspace key may never hold it.
 *   3. **The allowlist is explicit.** A JSON array of at most 1024 AGX-1.1 tool names, no wildcard.
 *   4. **`toolset_id` has no FK yet** — `agent_toolsets` is AGX-1.2 (#4530), which adds it.
 *   5. **Revocation is the existing soft delete**, so no revocation column is added.
 *
 * There is deliberately **no new RBAC resource**: the key API reuses `api_keys`.
 *
 * These must stay in lock-step with apiome-rest's `app.agent_keys` contract, its
 * `tests/test_agent_keys_migration.py` sibling, and apiome-mcp's `apiome_mcp.agent_access`.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V269__agent_keys_agx_3_1.sql";

let sql = "";
let lower = "";
/** The statements only — `--` comments and `COMMENT ON` prose removed — for negative checks. */
let ddl = "";

beforeAll(async () => {
  sql = await fs.readFile(path.join(SCRIPTS_DIR, MIGRATION), "utf8");
  lower = sql.toLowerCase();
  ddl = sql
    .replace(/--[^\n]*/g, "")
    .replace(/COMMENT ON [\s\S]*?;/g, "")
    .toLowerCase();
});

/**
 * The body of one named CHECK constraint, lower-cased and without comments.
 *
 * @param name The constraint name.
 * @returns Everything from `add constraint <name>` up to the statement's `;`.
 */
function constraint(name: string): string {
  const start = ddl.indexOf(`add constraint ${name}`);
  expect(start).toBeGreaterThanOrEqual(0);
  return ddl.slice(start, ddl.indexOf(";", start));
}

describe("agent keys migration (AGX-3.1)", () => {
  it("is present in scripts/ and ordered after the upstream vault migration", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files).toContain(MIGRATION);
    expect(files.indexOf(MIGRATION)).toBeGreaterThan(
      files.indexOf("V268__upstream_credentials_agx_2_2.sql"),
    );
  });

  it("targets the apiome schema and extends api_keys instead of adding a table", () => {
    expect(lower).toContain("set search_path to apiome, public");
    expect(ddl).toMatch(/alter table api_keys/);
    expect(ddl).not.toContain("create table");
  });

  it("adds the three columns idempotently, defaulting existing rows to workspace", () => {
    expect(ddl).toContain(
      "add column if not exists kind varchar(16) not null default 'workspace'",
    );
    expect(ddl).toContain("add column if not exists toolset_id uuid,");
    expect(ddl).toContain("add column if not exists tool_allowlist jsonb;");
  });

  it("reuses the V006 expires_at rather than adding a second expiry", () => {
    expect(ddl).not.toMatch(/add column if not exists expires_at/);
    expect(lower).toContain("expires_at      already present since v006");
  });

  it("drops each constraint before re-adding it, so a re-run is a no-op", () => {
    for (const name of [
      "api_keys_kind_ck",
      "api_keys_agent_binding_ck",
      "api_keys_agent_allowlist_ck",
      "api_keys_scopes_vocab_ck",
      "api_keys_kind_scopes_ck",
    ]) {
      expect(ddl).toContain(`drop constraint if exists ${name};`);
      expect(ddl).toContain(`add constraint ${name}`);
    }
  });

  describe("rule 1 — the two kinds are exclusive", () => {
    it("constrains kind to workspace and agent", () => {
      expect(constraint("api_keys_kind_ck")).toContain("check (kind in ('workspace', 'agent'))");
    });

    it("gives a toolset and an allowlist to agent keys, and neither to workspace keys", () => {
      const body = constraint("api_keys_agent_binding_ck");
      expect(body).toContain(
        "(kind = 'agent' and toolset_id is not null and tool_allowlist is not null)",
      );
      expect(body).toContain(
        "or (kind = 'workspace' and toolset_id is null and tool_allowlist is null)",
      );
    });
  });

  describe("rule 2 — an agent key is not a REST credential", () => {
    it("widens the V177 scope vocabulary by agent:invoke only", () => {
      expect(constraint("api_keys_scopes_vocab_ck")).toContain(
        "scopes <@ array['*', 'diff:read', 'lint:read', 'agent:invoke']::text[]",
      );
    });

    it("pins agent keys to exactly agent:invoke and keeps it off workspace keys", () => {
      const body = constraint("api_keys_kind_scopes_ck");
      expect(body).toContain("(kind = 'agent' and scopes = array['agent:invoke']::text[])");
      expect(body).toContain("or (kind = 'workspace' and not ('agent:invoke' = any (scopes)))");
    });
  });

  describe("rule 3 — the allowlist is explicit", () => {
    it("is a JSON array of at most 1024 entries", () => {
      const body = constraint("api_keys_agent_allowlist_ck");
      expect(body).toContain("jsonb_typeof(tool_allowlist) = 'array'");
      expect(body).toContain("jsonb_array_length(tool_allowlist) <= 1024");
    });

    it("holds only AGX-1.1 tool names, checked in strict mode", () => {
      expect(sql).toContain(
        `'strict $[*] ? (@.type() != "string" || !(@ like_regex "^[A-Za-z0-9_-]{1,64}$"))'`,
      );
    });

    it("has no wildcard entry", () => {
      expect(constraint("api_keys_agent_allowlist_ck")).not.toContain("'*'");
    });
  });

  describe("rule 4 — no toolset FK until AGX-1.2", () => {
    it("does not reference agent_toolsets", () => {
      expect(ddl).not.toContain("references agent_toolsets");
    });

    it("documents the AGX-1.2 handoff", () => {
      expect(sql).toContain("AGX-1.2 (#4530)");
      expect(sql).toContain("REFERENCES agent_toolsets(id)");
    });
  });

  describe("rule 5 — revocation is the existing soft delete", () => {
    it("adds no revocation column of its own", () => {
      expect(ddl).not.toContain("revoked_at");
    });

    it("indexes agent keys by prefix without excluding revoked rows", () => {
      expect(ddl).toContain("create index if not exists idx_api_keys_agent_prefix");
      expect(ddl).toMatch(/on api_keys \(key_prefix\)\s+where kind = 'agent';/);
    });

    it("indexes agent keys by tenant and toolset", () => {
      expect(ddl).toContain("create index if not exists idx_api_keys_agent_toolset");
      expect(ddl).toMatch(/on api_keys \(tenant_id, toolset_id\)\s+where kind = 'agent';/);
    });
  });

  it("documents the new columns and the widened scope vocabulary", () => {
    for (const column of ["kind", "toolset_id", "tool_allowlist", "scopes"]) {
      expect(lower).toContain(`comment on column api_keys.${column} is`);
    }
  });

  it("documents rollback", () => {
    expect(lower).toContain("drop column if exists tool_allowlist");
    expect(lower).toContain("drop column if exists toolset_id");
    expect(lower).toContain("drop column if exists kind");
    expect(lower).toContain("drop index if exists apiome.idx_api_keys_agent_prefix");
  });

  describe("no new RBAC resource", () => {
    it("leaves seed_builtin_roles and the permission tables alone", () => {
      expect(ddl).not.toContain("seed_builtin_roles");
      expect(ddl).not.toContain("role_permissions");
    });
  });
});
