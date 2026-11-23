/**
 * Structural assertions over the DBP-1.11 (#7194) index migrations, V412 to V417.
 *
 * Each migration adds the indexes a named query was missing, and some replace a narrower index the
 * new one covers. The promises pinned here: every statement is idempotent (so an operator can
 * pre-build the indexes with CREATE INDEX CONCURRENTLY and the migration then skips them), nothing
 * but an index is touched, a replaced index is dropped only after its replacement exists, and the
 * set of indexes is exactly the one the plan check justified.
 */

import fs from "node:fs/promises";
import path from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;

/** The migrations of DBP-1.11, in order. */
const MIGRATIONS = [
  "V412__versions_published_indexes_7194.sql",
  "V413__audit_keyset_indexes_7194.sql",
  "V414__job_and_run_indexes_7194.sql",
  "V415__document_store_indexes_7194.sql",
  "V416__catalog_and_mcp_indexes_7194.sql",
  "V417__auth_and_log_indexes_7194.sql",
];

/** Every index the migrations create, by table. */
const CREATED: Record<string, string[]> = {
  versions: ["idx_versions_public_published_recent", "idx_versions_project_published"],
  workflow_audit: [
    "idx_workflow_audit_project_created",
    "idx_workflow_audit_refresh_repository",
    "idx_workflow_audit_tenant_created_id",
  ],
  version_protection_audit: ["idx_version_protection_audit_project_created"],
  registry_audit: ["idx_registry_audit_tenant_created_id"],
  access_audit: ["idx_access_audit_tenant_created_id"],
  provider_check_runs: ["idx_provider_check_runs_project_created"],
  mcp_discovery_jobs: ["idx_mcp_discovery_jobs_endpoint_active"],
  tenant_repository_refresh_jobs: [
    "idx_tenant_repo_refresh_jobs_created",
    "idx_tenant_repo_refresh_jobs_lineage_finished",
  ],
  export_run_ledger: ["idx_export_run_ledger_tenant_actor_finished"],
  document_objects: [
    "idx_document_objects_verify_order",
    "idx_document_objects_unreferenced_since",
    "idx_document_objects_tenant_id_text",
  ],
  version_documents: ["idx_version_documents_rendered_created"],
  consumer_contract: ["idx_consumer_contract_tenant_current"],
  catalog_edges: ["idx_catalog_edges_tenant_from_id", "idx_catalog_edges_tenant_to_id"],
  mcp_endpoints: ["idx_mcp_endpoints_registry_server_name", "idx_mcp_endpoints_current_version"],
  verification: ["idx_verification_value"],
  session: ["idx_session_user_updated"],
  slate_insight_logs: ["idx_slate_insight_logs_message_trgm"],
};

/** Each replaced index and the index that replaces it. */
const REPLACED: Record<string, string> = {
  idx_workflow_audit_tenant_created_at: "idx_workflow_audit_tenant_created_id",
  idx_registry_audit_tenant_created_at: "idx_registry_audit_tenant_created_id",
  idx_access_audit_tenant_created_at: "idx_access_audit_tenant_created_id",
  idx_provider_check_runs_project_id_fk: "idx_provider_check_runs_project_created",
  idx_document_objects_unreferenced: "idx_document_objects_unreferenced_since",
  idx_document_objects_tenant: "idx_document_objects_tenant_id_text",
  idx_session_user_id: "idx_session_user_updated",
};

/** The SQL statements of each migration, lower-cased, comments stripped, whitespace collapsed. */
const statementsByFile = new Map<string, string[]>();

beforeAll(async () => {
  for (const file of MIGRATIONS) {
    const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
    statementsByFile.set(
      file,
      sql
        .toLowerCase()
        .split("\n")
        .map((line) => line.split("--")[0])
        .join("\n")
        .split(";")
        .map((statement) => statement.replace(/\s+/g, " ").trim())
        .filter(Boolean),
    );
  }
});

/** Every statement of every migration, in order. */
function allStatements(): string[] {
  return MIGRATIONS.flatMap((file) => statementsByFile.get(file) ?? []);
}

/**
 * The first capture group of `pattern` for each statement that matches it.
 *
 * @param statements - Normalized statements.
 * @param pattern - A regular expression with one capture group.
 * @returns The captured names, in statement order.
 */
function names(statements: string[], pattern: RegExp): string[] {
  return statements.flatMap((statement) => {
    const match = pattern.exec(statement);
    return match ? [match[1]] : [];
  });
}

describe("DBP-1.11 index migrations (V412-V417)", () => {
  it("run in order right after V411", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const start = files.indexOf("V411__import_pending_versions_7192.sql");
    expect(start).toBeGreaterThanOrEqual(0);
    expect(files.slice(start + 1, start + 1 + MIGRATIONS.length)).toEqual(MIGRATIONS);
  });

  it("only set the search path, drop indexes and create indexes, idempotently", () => {
    for (const statement of allStatements()) {
      expect(statement).toMatch(
        /^(set search_path to apiome, public|drop index if exists apiome\.\w+|create index if not exists \w+ on apiome\.\w+ (using gin )?\()/,
      );
    }
  });

  it("never create a unique index or build concurrently inside the migration", () => {
    for (const statement of allStatements()) {
      expect(statement).not.toMatch(/unique|concurrently/);
    }
  });

  it("create exactly the indexes the plan check justified, on the tables named", () => {
    const created = allStatements().flatMap((statement) => {
      const match = /^create index if not exists (\w+) on apiome\.(\w+) /.exec(statement);
      return match ? [`${match[2]}.${match[1]}`] : [];
    });
    const expected = Object.entries(CREATED).flatMap(([table, list]) => list.map((name) => `${table}.${name}`));
    expect([...created].sort()).toEqual([...expected].sort());
    expect(new Set(created).size).toBe(created.length);
    for (const name of created) {
      expect(name.split(".")[1].length).toBeLessThanOrEqual(63);
    }
  });

  it("drop a replaced index only after creating its replacement in the same migration", () => {
    let dropped = 0;
    for (const file of MIGRATIONS) {
      const statements = statementsByFile.get(file) ?? [];
      statements.forEach((statement, position) => {
        const match = /^drop index if exists apiome\.(\w+)$/.exec(statement);
        if (!match) return;
        dropped += 1;
        const replacement = REPLACED[match[1]];
        expect(replacement, `${file} drops ${match[1]}, which has no replacement listed`).toBeDefined();
        const createdAt = statements.findIndex((s) => s.startsWith(`create index if not exists ${replacement} `));
        expect(createdAt, `${file} drops ${match[1]} before creating ${replacement}`).toBeGreaterThanOrEqual(0);
        expect(createdAt).toBeLessThan(position);
      });
    }
    expect(dropped).toBe(Object.keys(REPLACED).length);
  });

  it("never drop an index they create", () => {
    const created = new Set(names(allStatements(), /^create index if not exists (\w+)/));
    for (const name of names(allStatements(), /^drop index if exists apiome\.(\w+)/)) {
      expect(created.has(name)).toBe(false);
    }
  });

  it("set the search path before the trigram index so gin_trgm_ops resolves", () => {
    const statements = statementsByFile.get("V417__auth_and_log_indexes_7194.sql") ?? [];
    const searchPath = statements.indexOf("set search_path to apiome, public");
    const trigram = statements.findIndex((s) => s.includes("gin_trgm_ops"));
    expect(searchPath).toBeGreaterThanOrEqual(0);
    expect(trigram).toBeGreaterThan(searchPath);
  });

  it("keep the versions indexes partial, so drafts and private revisions get no entry", () => {
    const statements = statementsByFile.get("V412__versions_published_indexes_7194.sql") ?? [];
    expect(statements).toHaveLength(2);
    for (const statement of statements) {
      expect(statement).toMatch(/ where published and .*deleted_at is null$/);
    }
  });
});
