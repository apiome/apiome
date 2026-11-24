/**
 * DBP-1.27 (#7210), migration V431: the public-catalog summary table and the stored MCP host.
 *
 * Two layers:
 *   1. Structural promises of the migration (order, table, triggers, indexes, the view).
 *   2. Behaviour, on a migrated database: after every kind of write that can change the public
 *      catalog — publish, unpublish, visibility change, soft and hard delete, restore, a move, a
 *      tenant delete, a statement over many versions — `apiome.browse_public_projects` equals the
 *      aggregate it stands for.
 *
 * Layer 2 needs `APIOME_DB_SCHEMA_TEST_URL` pointing at a database migrated to the current head;
 * without it the block is skipped. Each test runs in a transaction that is rolled back. Locally:
 *
 *     createdb apiome_t && node dist/cli.js migrate --database-url postgresql://localhost/apiome_t
 *     APIOME_DB_SCHEMA_TEST_URL=postgresql://localhost/apiome_t yarn vitest run test/browse-public-projects.test.ts
 */

import fs from "node:fs/promises";
import path from "node:path";

import pg from "pg";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V431__browse_public_projects_7210.sql";
const PREVIOUS = "V430__mock_session_one_row_per_session_7209.sql";
const SCHEMA_TEST_URL = process.env.APIOME_DB_SCHEMA_TEST_URL?.trim() ?? "";

/** A migration's SQL with `--` comments stripped and whitespace collapsed, lower-cased. */
async function codeOf(file: string): Promise<string> {
  const sql = await fs.readFile(path.join(SCRIPTS_DIR, file), "utf8");
  return sql
    .split("\n")
    .map((line) => line.split("--")[0])
    .join("\n")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

describe("V431: public-catalog summary and stored MCP host", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows the DBP-1.26 migration in order", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    expect(files.indexOf(MIGRATION)).toBe(files.indexOf(PREVIOUS) + 1);
  });

  it("keys the summary by project, cascading with it, and copies the tenant without a foreign key", () => {
    expect(code).toContain(
      "project_id uuid primary key references apiome.projects(id) on delete cascade",
    );
    expect(code).toContain("tenant_id uuid not null,");
    expect(code).not.toContain("references apiome.tenants");
    expect(code).not.toContain("references apiome.versions");
  });

  it("applies the Browse gates: published, public, and nothing deleted", () => {
    const refresh = code.slice(
      code.indexOf("create or replace function apiome.refresh_browse_public_projects"),
      code.indexOf("create or replace function apiome.trg_versions_browse_public"),
    );
    expect(refresh).toContain("p.deleted_at is null");
    expect(refresh).toContain("t.deleted_at is null");
    expect(refresh).toContain("v.published = true and v.visibility = 'public' and v.deleted_at is null");
    // The latest version, in the order every Browse surface uses.
    expect(refresh).toContain("order by l.published_at desc nulls last, l.created_at desc, l.id desc limit 1");
    // One refresh of a project at a time, without blocking version inserts.
    expect(refresh).toContain("for no key update");
    // A row is written only when a value differs.
    expect(refresh).toContain("is distinct from");
  });

  it("maintains it from statement triggers on versions, with transition tables", () => {
    expect(code).toContain(
      "create trigger trg_versions_browse_public_insert after insert on apiome.versions referencing new table as new_rows for each statement",
    );
    expect(code).toContain(
      "create trigger trg_versions_browse_public_update after update on apiome.versions referencing old table as old_rows new table as new_rows for each statement",
    );
    expect(code).toContain(
      "create trigger trg_versions_browse_public_delete after delete on apiome.versions referencing old table as old_rows for each statement",
    );
  });

  it("defers the refresh after a content write to commit, when the transaction's content is all there", () => {
    expect(code).toContain(
      "create constraint trigger trg_versions_browse_public_content after update on apiome.versions deferrable initially deferred for each row when (old.content_stamp is distinct from new.content_stamp and new.published and new.visibility = 'public' and new.deleted_at is null)",
    );
  });

  it("follows the project and the tenant", () => {
    expect(code).toContain(
      "create trigger trg_projects_browse_public after update of deleted_at, tenant_id on apiome.projects for each row",
    );
    expect(code).toContain(
      "create trigger trg_tenants_browse_public after update of deleted_at on apiome.tenants for each row",
    );
  });

  it("does not write versions, so no content stamp moves", () => {
    expect(code).not.toContain("update apiome.versions");
    expect(code).not.toContain("bump_version_content_stamp");
  });

  it("indexes the organization lookup and the three rail orders", () => {
    expect(code).toContain("on apiome.browse_public_projects (tenant_id)");
    expect(code).toContain(
      "on apiome.browse_public_projects (version_count desc, latest_published_at desc nulls last)",
    );
    expect(code).toContain(
      "on apiome.browse_public_projects (operation_count desc, version_count desc, latest_published_at desc nulls last)",
    );
    expect(code).toContain(
      "on apiome.browse_public_projects (quality_grade asc nulls last, quality_score desc nulls last, latest_published_at desc nulls last)",
    );
  });

  it("stores the MCP host with the view's expression and reads it in the view", async () => {
    const expression = "substring(endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)')";
    expect(code).toContain(`add column if not exists host text generated always as (${expression}) stored`);
    // The same expression V134 computed per read.
    expect(await codeOf("V134__mcp_catalog_public_endpoints_view_3671.sql")).toContain(
      "substring(e.endpoint_url from '://(?:[^@/]*@)?([^:/?#]+)') as host",
    );
    const view = code.slice(code.indexOf("create or replace view apiome.mcp_v_public_endpoints"));
    expect(view).toContain("e.current_version_id, e.host, s.score,");
    expect(view).not.toContain("endpoint_url");
  });

  it("indexes public endpoints by host, lower(host) and registry server name, under the view's predicates", () => {
    const predicate =
      "where deleted_at is null and enabled is true and published is true and visibility = 'public'::apiome.visibility_type";
    expect(code).toContain(`on apiome.mcp_endpoints (host, id) ${predicate}`);
    expect(code).toContain(`on apiome.mcp_endpoints (lower(host)) ${predicate}`);
    expect(code).toContain(`on apiome.mcp_endpoints (lower(registry_metadata->>'servername')) ${predicate}`);
  });
});

describe.skipIf(!SCHEMA_TEST_URL)("V431 on a migrated database", () => {
  let client: pg.Client;
  let userId = "";
  let tenantId = "";
  let projectId = "";

  beforeAll(async () => {
    client = new pg.Client({ connectionString: SCHEMA_TEST_URL });
    await client.connect();
  });
  afterAll(async () => {
    await client.end();
  });

  beforeEach(async () => {
    await client.query("BEGIN");
    const tag = Math.random().toString(36).slice(2, 10);
    userId = (
      await client.query(
        "INSERT INTO apiome.users (name, email, password) VALUES ('Summary', $1, 'x') RETURNING id",
        [`summary-${tag}@apiome.local`],
      )
    ).rows[0].id;
    tenantId = await addTenant(`summary-${tag}`);
    projectId = await addProject("Payments");
  });
  afterEach(async () => {
    await client.query("ROLLBACK");
  });

  async function addTenant(slug: string): Promise<string> {
    return (await client.query("INSERT INTO apiome.tenants (name, slug) VALUES ('Summary', $1) RETURNING id", [slug]))
      .rows[0].id;
  }

  async function addProject(name: string, tenant = tenantId): Promise<string> {
    const res = await client.query(
      "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES ($1, $2, $3, $4) RETURNING id",
      [tenant, userId, name, `${name.toLowerCase()}-${Math.random().toString(36).slice(2, 8)}`],
    );
    return res.rows[0].id;
  }

  /** `2026-11-<day>` at noon UTC. */
  function day(n: number): string {
    return `2026-11-${String(n).padStart(2, "0")}T12:00:00Z`;
  }

  async function addVersion(
    label: string,
    opts: {
      published?: boolean;
      visibility?: string;
      publishedAt?: string | null;
      project?: string;
      protocol?: string | null;
      format?: string | null;
    } = {},
  ): Promise<string> {
    const published = opts.published ?? true;
    const res = await client.query(
      `INSERT INTO apiome.versions (project_id, creator_id, version_id, published, visibility, published_at, protocol, source_format)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id`,
      [
        opts.project ?? projectId,
        userId,
        label,
        published,
        opts.visibility ?? "public",
        opts.publishedAt === undefined ? (published ? day(2) : null) : opts.publishedAt,
        opts.protocol === undefined ? "REST" : opts.protocol,
        opts.format === undefined ? "OpenAPI-3.1" : opts.format,
      ],
    );
    return res.rows[0].id;
  }

  async function summary(project = projectId) {
    const res = await client.query("SELECT * FROM apiome.browse_public_projects WHERE project_id = $1", [project]);
    return res.rows[0] ?? null;
  }

  /**
   * The invariant, over every project of the test user: the stored row is the aggregate of the
   * project's published public versions, and there is a row exactly when that aggregate is not
   * empty and neither the project nor its tenant is deleted.
   */
  async function expectConsistent(): Promise<void> {
    const res = await client.query(
      `SELECT p.id, to_jsonb(b) - 'project_id' AS stored,
              CASE WHEN w.version_count IS NULL THEN NULL ELSE to_jsonb(w) END AS want
         FROM apiome.projects p
         LEFT JOIN apiome.browse_public_projects b ON b.project_id = p.id
         LEFT JOIN LATERAL (
           SELECT p.tenant_id, a.version_count, lv.id AS latest_version_id,
                  lv.published_at AS latest_published_at, a.protocols, a.formats,
                  (SELECT COUNT(*)::int FROM apiome.version_path vp
                     JOIN apiome.path_operation po ON po.version_path_id = vp.id
                    WHERE vp.version_id = lv.id) AS operation_count,
                  (SELECT COUNT(*)::int FROM apiome.classes c
                    WHERE c.version_id = lv.id AND c.deleted_at IS NULL) AS schema_count,
                  NULLIF(TRIM(lv.quality_grade), '') AS quality_grade,
                  lv.quality_score::int AS quality_score
             FROM (
               SELECT COUNT(*)::int AS version_count,
                      COALESCE(array_agg(DISTINCT LOWER(TRIM(v.protocol)) ORDER BY LOWER(TRIM(v.protocol)))
                        FILTER (WHERE TRIM(COALESCE(v.protocol, '')) <> ''), ARRAY[]::text[]) AS protocols,
                      COALESCE(array_agg(DISTINCT LOWER(TRIM(v.source_format)) ORDER BY LOWER(TRIM(v.source_format)))
                        FILTER (WHERE TRIM(COALESCE(v.source_format, '')) <> ''), ARRAY[]::text[]) AS formats
                 FROM apiome.versions v
                WHERE v.project_id = p.id AND v.published AND v.visibility = 'public' AND v.deleted_at IS NULL
               HAVING COUNT(*) > 0
             ) a
             JOIN LATERAL (
               SELECT l.* FROM apiome.versions l
                WHERE l.project_id = p.id AND l.published AND l.visibility = 'public' AND l.deleted_at IS NULL
                ORDER BY l.published_at DESC NULLS LAST, l.created_at DESC, l.id DESC LIMIT 1
             ) lv ON TRUE
            WHERE p.deleted_at IS NULL
              AND EXISTS (SELECT 1 FROM apiome.tenants t WHERE t.id = p.tenant_id AND t.deleted_at IS NULL)
         ) w ON TRUE
        WHERE p.creator_id = $1`,
      [userId],
    );
    expect(res.rows.length).toBeGreaterThan(0);
    for (const row of res.rows) expect(row.stored).toEqual(row.want);
  }

  it("has no row for a project of drafts or of private versions", async () => {
    await addVersion("0.1.0", { published: false });
    await addVersion("0.2.0", { visibility: "private" });
    expect(await summary()).toBeNull();
    await expectConsistent();
  });

  it("summarizes a version inserted already published", async () => {
    const v = await addVersion("1.0.0");
    const row = await summary();
    expect(row).toMatchObject({
      tenant_id: tenantId,
      version_count: 1,
      latest_version_id: v,
      protocols: ["rest"],
      formats: ["openapi-3.1"],
      operation_count: 0,
      schema_count: 0,
    });
    await expectConsistent();
  });

  it("follows a publish and an unpublish", async () => {
    const v = await addVersion("1.0.0", { published: false });
    expect(await summary()).toBeNull();

    await client.query("UPDATE apiome.versions SET published = true, published_at = $2 WHERE id = $1", [v, day(3)]);
    expect((await summary()).version_count).toBe(1);
    await expectConsistent();

    await client.query("UPDATE apiome.versions SET published = false WHERE id = $1", [v]);
    expect(await summary()).toBeNull();
    await expectConsistent();
  });

  it("follows a visibility change", async () => {
    const v = await addVersion("1.0.0");
    await client.query("UPDATE apiome.versions SET visibility = 'private' WHERE id = $1", [v]);
    expect(await summary()).toBeNull();
    await client.query("UPDATE apiome.versions SET visibility = 'public' WHERE id = $1", [v]);
    expect((await summary()).latest_version_id).toBe(v);
    await expectConsistent();
  });

  it("picks the latest version by published_at, then created_at, and rolls up protocols and formats", async () => {
    await addVersion("1.0.0", { publishedAt: day(2), protocol: "REST", format: "openapi-3.0" });
    const newest = await addVersion("2.0.0", { publishedAt: day(5), protocol: " GraphQL ", format: "GraphQL-SDL" });
    await addVersion("1.5.0", { publishedAt: day(3), protocol: null, format: "" });
    await addVersion("3.0.0-draft", { published: false, protocol: "grpc", format: "protobuf" });

    const row = await summary();
    expect(row.version_count).toBe(3);
    expect(row.latest_version_id).toBe(newest);
    expect(row.latest_published_at.toISOString()).toBe(new Date(day(5)).toISOString());
    expect(row.protocols).toEqual(["graphql", "rest"]);
    expect(row.formats).toEqual(["graphql-sdl", "openapi-3.0"]);
    await expectConsistent();
  });

  it("follows a soft delete and a hard delete of a version", async () => {
    const first = await addVersion("1.0.0", { publishedAt: day(2) });
    const second = await addVersion("2.0.0", { publishedAt: day(3) });

    await client.query("UPDATE apiome.versions SET deleted_at = now() WHERE id = $1", [second]);
    expect(await summary()).toMatchObject({ version_count: 1, latest_version_id: first });
    await expectConsistent();

    await client.query("DELETE FROM apiome.versions WHERE id = $1", [first]);
    expect(await summary()).toBeNull();
    await expectConsistent();
  });

  it("follows one statement over many versions (retention pruning)", async () => {
    const other = await addProject("Billing");
    for (let n = 1; n <= 4; n += 1) {
      await addVersion(`1.${n}.0`, { publishedAt: day(n) });
      await addVersion(`1.${n}.0`, { publishedAt: day(n), project: other });
    }
    await client.query(
      `UPDATE apiome.versions v SET deleted_at = now()
         FROM apiome.projects p
        WHERE p.id = v.project_id AND p.creator_id = $1 AND v.published_at < $2`,
      [userId, day(3)],
    );
    expect((await summary()).version_count).toBe(2);
    expect((await summary(other)).version_count).toBe(2);
    await expectConsistent();
  });

  it("follows the project: soft delete, restore and hard delete", async () => {
    await addVersion("1.0.0");
    await client.query("UPDATE apiome.projects SET deleted_at = now() WHERE id = $1", [projectId]);
    expect(await summary()).toBeNull();
    await expectConsistent();

    await client.query("UPDATE apiome.projects SET deleted_at = NULL WHERE id = $1", [projectId]);
    expect((await summary()).version_count).toBe(1);
    await expectConsistent();

    await client.query("DELETE FROM apiome.projects WHERE id = $1", [projectId]);
    expect(await summary()).toBeNull();
  });

  it("follows the tenant: soft delete and restore", async () => {
    await addVersion("1.0.0");
    const other = await addProject("Billing");
    await addVersion("1.0.0", { project: other });

    await client.query("UPDATE apiome.tenants SET deleted_at = now() WHERE id = $1", [tenantId]);
    expect(await summary()).toBeNull();
    expect(await summary(other)).toBeNull();
    await expectConsistent();

    await client.query("UPDATE apiome.tenants SET deleted_at = NULL WHERE id = $1", [tenantId]);
    expect(await summary()).not.toBeNull();
    expect(await summary(other)).not.toBeNull();
    await expectConsistent();
  });

  it("moves with a version that changes project, and with a project that changes tenant", async () => {
    const v = await addVersion("1.0.0");
    const other = await addProject("Billing");
    await client.query("UPDATE apiome.versions SET project_id = $2 WHERE id = $1", [v, other]);
    expect(await summary()).toBeNull();
    expect((await summary(other)).latest_version_id).toBe(v);

    const otherTenant = await addTenant(`summary-moved-${Math.random().toString(36).slice(2, 8)}`);
    await client.query("UPDATE apiome.projects SET tenant_id = $2 WHERE id = $1", [other, otherTenant]);
    expect((await summary(other)).tenant_id).toBe(otherTenant);
    await expectConsistent();
  });

  it("follows the latest version's grade and its content", async () => {
    const v = await addVersion("1.0.0");
    expect(await summary()).toMatchObject({ schema_count: 0, quality_grade: null });

    await client.query("UPDATE apiome.versions SET quality_grade = ' B ', quality_score = 82 WHERE id = $1", [v]);
    expect(await summary()).toMatchObject({ quality_grade: "B", quality_score: 82 });

    // Two content writes in one transaction: only the first moves content_stamp and clears the
    // stored count (V403, V424). The refresh waits for commit, so it counts both.
    await client.query("INSERT INTO apiome.classes (version_id, name, schema) VALUES ($1, 'Payment', '{}'::jsonb)", [v]);
    await client.query("INSERT INTO apiome.classes (version_id, name, schema) VALUES ($1, 'Refund', '{}'::jsonb)", [v]);
    await client.query("SET CONSTRAINTS ALL IMMEDIATE"); // what COMMIT does
    expect((await summary()).schema_count).toBe(2);
    await expectConsistent();
  });

  it("leaves the summary alone when a draft or a bookkeeping column changes", async () => {
    const live = await addVersion("1.0.0");
    const draft = await addVersion("2.0.0-draft", { published: false });
    const before = await client.query(
      "SELECT xmin::text AS xmin, ctid::text AS ctid FROM apiome.browse_public_projects WHERE project_id = $1",
      [projectId],
    );

    await client.query("UPDATE apiome.versions SET description = 'edited', protocol = 'grpc' WHERE id = $1", [draft]);
    await client.query("UPDATE apiome.versions SET updated_at = now() WHERE id = $1", [live]);
    await client.query("SELECT apiome.refresh_browse_public_projects(ARRAY[$1::uuid])", [projectId]);

    const after = await client.query(
      "SELECT xmin::text AS xmin, ctid::text AS ctid FROM apiome.browse_public_projects WHERE project_id = $1",
      [projectId],
    );
    expect(after.rows).toEqual(before.rows);
    await expectConsistent();
  });

  it("ignores ids of projects that do not exist, and an empty list", async () => {
    await client.query("SELECT apiome.refresh_browse_public_projects(ARRAY[gen_random_uuid()])");
    await client.query("SELECT apiome.refresh_browse_public_projects(ARRAY[]::uuid[])");
    await client.query("SELECT apiome.refresh_browse_public_projects(NULL)");
  });

  it("stores the MCP host the view shows, userinfo stripped", async () => {
    const res = await client.query(
      `INSERT INTO apiome.mcp_endpoints (tenant_id, creator_id, name, slug, endpoint_url, transport, visibility, published, enabled)
       VALUES ($1, $2, 'Docs', $3, 'https://user:secret@MCP.Example.com:8443/mcp', 'streamable_http', 'public', true, true)
       RETURNING id, host`,
      [tenantId, userId, `docs-${Math.random().toString(36).slice(2, 8)}`],
    );
    expect(res.rows[0].host).toBe("MCP.Example.com");
    const view = await client.query("SELECT host FROM apiome.mcp_v_public_endpoints WHERE id = $1", [res.rows[0].id]);
    expect(view.rows[0].host).toBe("MCP.Example.com");
  });
});
