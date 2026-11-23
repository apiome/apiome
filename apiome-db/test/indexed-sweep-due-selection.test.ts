/**
 * Structural assertions over the DBP-1.18 (#7201) migration, V426:
 *
 *   - a stored "next due" column per swept table (MCP discovery, repository refresh, catalog
 *     digests) kept current by BEFORE triggers on exactly the columns it depends on;
 *   - branch-rule changes move their repository's due instant;
 *   - the stored latest health probe, backfilled once;
 *   - partial indexes whose predicates match the REST due queries, with COALESCE(-infinity)
 *     expression indexes for rows that have never run;
 *   - the retention indexes for finished discovery jobs and the digest's time-window index.
 *
 * Behaviour (the triggers, the due queries, the plans on the scale database) is tested against
 * Postgres in apiome-rest (tests/test_sweep_due_selection_db.py); these tests keep the definitions
 * from drifting.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V426__indexed_sweep_due_selection_7201.sql";

/** The migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

describe("V426: indexed sweep due-selection", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows V425", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf("V425__mcp_version_derived_facts_7200.sql");
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  it("adds nullable columns only, so no table is rewritten", () => {
    for (const column of ["discovery_due_at", "last_health_checked_at", "refresh_due_at", "digest_due_at"]) {
      expect(code, column).toContain(`add column if not exists ${column} timestamp with time zone`);
      expect(code, column).not.toMatch(new RegExp(`add column if not exists ${column} [^,;]*(default|not null|generated)`));
    }
  });

  describe("triggers", () => {
    const triggers: Array<[string, string, string]> = [
      [
        "trg_mcp_endpoints_discovery_due",
        "before insert or update of last_discovered_at, discovery_cadence_seconds, next_discovery_after on apiome.mcp_endpoints",
        "apiome.mcp_endpoints_set_discovery_due()",
      ],
      [
        "trg_tenant_repositories_refresh_due",
        "before insert or update of last_refreshed_at, refresh_interval_seconds on apiome.tenant_repositories",
        "apiome.tenant_repositories_set_refresh_due()",
      ],
      [
        "trg_repository_branch_refresh_rule_due",
        "after insert or delete or update of repository_id, refresh_enabled, refresh_interval_seconds on apiome.repository_branch_refresh_rule",
        "apiome.repository_branch_refresh_rule_touch_due()",
      ],
      [
        "trg_mcp_catalog_digest_configs_due",
        "before insert or update of last_digest_at, cadence_seconds on apiome.mcp_catalog_digest_configs",
        "apiome.mcp_catalog_digest_configs_set_due()",
      ],
    ];

    it.each(triggers)("%s fires on the columns its due instant depends on", (name, timing, fn) => {
      expect(code).toContain(`create trigger ${name} ${timing} for each row execute function ${fn}`);
      expect(code).toContain(`drop trigger if exists ${name}`);
    });

    it("leaves discovery_due_at NULL for an endpoint on the global default cadence", () => {
      expect(code).toContain("if new.discovery_cadence_seconds is null then new.discovery_due_at := null;");
      expect(code).toContain("coalesce(new.next_discovery_after, '-infinity'::timestamptz)");
    });

    it("folds the shortest enabled branch rule into the repository's due instant", () => {
      expect(code).toContain("when p_last_refreshed_at is null then '-infinity'::timestamptz");
      expect(code).toContain("least( p_interval_seconds, (select min(r.refresh_interval_seconds)");
      expect(code).toContain("where r.repository_id = p_repository_id and r.refresh_enabled");
    });
  });

  describe("indexes", () => {
    const indexes: Array<[string, string]> = [
      [
        "idx_mcp_endpoints_discovery_due",
        "on apiome.mcp_endpoints (discovery_due_at) where deleted_at is null and enabled and quarantined_at is null and discovery_cadence_seconds is not null",
      ],
      [
        "idx_mcp_endpoints_discovery_due_default",
        "on apiome.mcp_endpoints ((coalesce(last_discovered_at, '-infinity'::timestamptz))) where deleted_at is null and enabled and quarantined_at is null and discovery_cadence_seconds is null",
      ],
      [
        "idx_mcp_endpoints_health_due",
        "on apiome.mcp_endpoints ((coalesce(last_health_checked_at, '-infinity'::timestamptz)), created_at) where deleted_at is null and enabled and transport <> 'stdio'",
      ],
      [
        "idx_tenant_repositories_refresh_due",
        "on apiome.tenant_repositories (refresh_due_at, created_at) where deleted_at is null and status in ('ready', 'error') and auto_refresh_enabled and refresh_paused_at is null",
      ],
      [
        "idx_mcp_catalog_digest_configs_due",
        "on apiome.mcp_catalog_digest_configs (digest_due_at) where enabled and cadence_seconds is not null",
      ],
      [
        "idx_mcp_catalog_digest_configs_due_default",
        "on apiome.mcp_catalog_digest_configs ((coalesce(last_digest_at, '-infinity'::timestamptz))) where enabled and cadence_seconds is null",
      ],
      [
        "idx_mcp_discovery_jobs_terminal_created",
        "on apiome.mcp_discovery_jobs (created_at, id) where state in ('completed', 'failed')",
      ],
      [
        "idx_mcp_discovery_jobs_terminal_endpoint",
        "on apiome.mcp_discovery_jobs (endpoint_id, created_at desc, id desc) where state in ('completed', 'failed')",
      ],
      [
        "idx_mcp_endpoint_versions_endpoint_moved_at",
        "on apiome.mcp_endpoint_versions (endpoint_id, (coalesce(discovered_at, created_at)))",
      ],
    ];

    it.each(indexes)("%s matches the REST due query", (name, definition) => {
      expect(code).toContain(`create index if not exists ${name} ${definition}`);
    });
  });

  it("backfills every due column and the latest health probe", () => {
    expect(code).toContain("update apiome.mcp_endpoints set discovery_due_at = greatest(");
    expect(code).toContain("select endpoint_id, max(checked_at) as last_checked_at from apiome.mcp_endpoint_health_checks group by endpoint_id");
    expect(code).toContain("update apiome.tenant_repositories t set refresh_due_at = apiome.tenant_repository_refresh_due_at(");
    expect(code).toContain("update apiome.mcp_catalog_digest_configs set digest_due_at = coalesce(");
  });
});
