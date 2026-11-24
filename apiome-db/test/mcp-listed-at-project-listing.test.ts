/**
 * DBP-1.22 (#7205), migration V428: the stored MCP listing key and the per-project rollup.
 *
 * Two layers:
 *   1. Structural promises of the migration (order, column, indexes, trigger column lists, the
 *      content-stamp function changed in one place only).
 *   2. Behaviour, on a migrated database: after every kind of write that can change what the MCP
 *      catalog lists, `versions.mcp_listed_at` equals the `updated_at` of `apiome.mcp_v_public_specs`
 *      (for public revisions), is NULL exactly for revisions the catalog cannot list, and
 *      `apiome.mcp_project_listing` equals the aggregate it stands for.
 *
 * Layer 2 needs `APIOME_DB_SCHEMA_TEST_URL` pointing at a database migrated to the current head
 * (CI's `schema` job in .github/workflows/apiome-db.yml starts one); without it the block is
 * skipped. Each test runs in a transaction that is rolled back. Locally:
 *
 *     createdb apiome_t && node dist/cli.js migrate --database-url postgresql://localhost/apiome_t
 *     APIOME_DB_SCHEMA_TEST_URL=postgresql://localhost/apiome_t yarn vitest run test/mcp-listed-at-project-listing.test.ts
 */

import fs from "node:fs/promises";
import path from "node:path";

import pg from "pg";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { listMigrationFiles } from "../src/migrate.js";

const SCRIPTS_DIR = new URL("../scripts", import.meta.url).pathname;
const MIGRATION = "V428__mcp_listed_at_and_project_listing_7205.sql";
const PREVIOUS_STAMP = "V427__content_stamp_statement_triggers_7202.sql";
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

/** The `bump_version_content_stamp` function definition in a migration. */
function stampFunction(code: string): string {
  const start = code.indexOf("create or replace function apiome.bump_version_content_stamp()");
  const end = code.indexOf("$fn$;", start);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  return code.slice(start, end);
}

describe("V428: MCP listing key and project rollup", () => {
  let code = "";
  beforeAll(async () => {
    code = await codeOf(MIGRATION);
  });

  it("follows the DBP-1.19 migration in order", async () => {
    const files = await listMigrationFiles(SCRIPTS_DIR);
    const previous = files.indexOf(PREVIOUS_STAMP);
    expect(previous).toBeGreaterThan(-1);
    expect(files.indexOf(MIGRATION)).toBe(previous + 1);
  });

  it("adds a nullable timestamp without rewriting versions", () => {
    expect(code).toContain("alter table apiome.versions add column if not exists mcp_listed_at timestamptz null;");
    expect(code).not.toMatch(/mcp_listed_at timestamptz[^;]*(default|generated)/);
  });

  it("computes the timestamp with the view's expression, for every visibility", () => {
    const start = code.indexOf("create or replace function apiome.compute_mcp_listed_at_for_version");
    const fn = code.slice(start, code.indexOf("$$;", start));
    expect(fn).toContain("greatest( v.updated_at, p.updated_at, coalesce(");
    expect(fn).toContain("'-infinity'::timestamptz");
    for (const rule of [
      "v.deleted_at is null",
      "p.deleted_at is null",
      "v.enabled is true",
      "p.enabled is true",
      "v.published is true",
    ]) {
      expect(fn).toContain(rule);
    }
    // Private revisions are listed too (to their own tenant's keys): visibility is not a condition.
    expect(fn).not.toContain("visibility");
  });

  it("creates the two listing indexes and the two rollup indexes", () => {
    for (const definition of [
      "create index if not exists idx_versions_mcp_public_listed on apiome.versions (mcp_listed_at desc, id desc) where mcp_listed_at is not null and visibility = 'public';",
      "create index if not exists idx_versions_mcp_project_listed on apiome.versions (project_id, mcp_listed_at desc, id desc) where mcp_listed_at is not null;",
      "create index if not exists idx_mcp_project_listing_public on apiome.mcp_project_listing (public_listed_at desc, tenant_id desc, project_id desc) where public_listed_at is not null;",
      "create index if not exists idx_mcp_project_listing_tenant on apiome.mcp_project_listing (tenant_id, listed_at desc, project_id desc) where listed_at is not null;",
    ]) {
      expect(code).toContain(definition);
    }
  });

  it("moves the HNSW index onto the public listed revisions", () => {
    expect(code).toContain(
      "create index if not exists idx_versions_mcp_public_listed_embedding_hnsw on apiome.versions using hnsw (mcp_public_embedding vector_cosine_ops) where mcp_public_embedding is not null and mcp_listed_at is not null and visibility = 'public';",
    );
    expect(code).toContain("drop index if exists apiome.idx_versions_mcp_public_embedding_hnsw;");
    // The new index exists before the old one goes.
    expect(code.indexOf("idx_versions_mcp_public_listed_embedding_hnsw")).toBeLessThan(
      code.indexOf("drop index if exists apiome.idx_versions_mcp_public_embedding_hnsw"),
    );
  });

  it("keys the rollup by project, cascading with it", () => {
    expect(code).toContain(
      "create table if not exists apiome.mcp_project_listing ( project_id uuid primary key references apiome.projects(id) on delete cascade,",
    );
  });

  it("fires the revision and project triggers on updated_at as well", () => {
    expect(code).toContain(
      "after insert or update of description, version_id, enabled, published, deleted_at, visibility, project_id, updated_at on apiome.versions",
    );
    expect(code).toContain("after update of name, enabled, deleted_at, updated_at, tenant_id on apiome.projects");
    expect(code).toContain(
      "create trigger trg_versions_delete_mcp_project_listing after delete on apiome.versions for each row when (old.mcp_listed_at is not null)",
    );
  });

  it("writes a revision only when its search document or timestamp changes", () => {
    const start = code.indexOf("create or replace function apiome.refresh_mcp_listing_for_version");
    const fn = code.slice(start, code.indexOf("$$;", start));
    expect(fn).toContain(
      "and (v.mcp_public_doc_tsv is distinct from n.doc_tsv or v.mcp_listed_at is distinct from n.listed_at)",
    );
  });

  it("re-creates the content-stamp function with mcp_listed_at ignored and nothing else changed", async () => {
    const fn = stampFunction(code);
    expect(fn).toContain("'operation_count', 'schema_count', 'mcp_listed_at'];");
    const normalized = fn.replace(", 'mcp_listed_at'];", "];");
    expect(normalized).toBe(stampFunction(await codeOf(PREVIOUS_STAMP)));
  });

  it("backfills in one pass that names only the new column", () => {
    const start = code.indexOf("update apiome.versions v set mcp_listed_at = greatest(");
    expect(start).toBeGreaterThan(-1);
    const statement = code.slice(start, code.indexOf(";", start));
    expect(statement).toContain("and v.mcp_listed_at is null");
    expect(statement).not.toContain("mcp_public_doc_tsv");
  });
});

// ───────────────────────────── behaviour on a migrated database ─────────────────────────────

const T0 = "2026-03-01T00:00:00Z";
/** Day `n` after T0 as the ISO string the helpers below return (no milliseconds). */
const day = (n: number) => new Date(Date.parse(T0) + n * 86_400_000).toISOString().replace(".000Z", "Z");

describe.skipIf(!SCHEMA_TEST_URL)("V428 on a migrated database", () => {
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
        "INSERT INTO apiome.users (name, email, password) VALUES ('Listing', $1, 'x') RETURNING id",
        [`listing-${tag}@apiome.local`],
      )
    ).rows[0].id;
    tenantId = (
      await client.query("INSERT INTO apiome.tenants (name, slug) VALUES ('Listing', $1) RETURNING id", [
        `listing-${tag}`,
      ])
    ).rows[0].id;
    projectId = await addProject("Payments", day(1));
  });
  afterEach(async () => {
    await client.query("ROLLBACK");
  });

  async function addProject(name: string, updatedAt: string): Promise<string> {
    const res = await client.query(
      "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, updated_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
      [tenantId, userId, name, `${name.toLowerCase()}-${Math.random().toString(36).slice(2, 8)}`, updatedAt],
    );
    return res.rows[0].id;
  }

  async function addVersion(
    label: string,
    opts: { published?: boolean; visibility?: string; updatedAt?: string; project?: string } = {},
  ): Promise<string> {
    const res = await client.query(
      `INSERT INTO apiome.versions (project_id, creator_id, version_id, description, published, visibility, enabled, updated_at)
       VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7) RETURNING id`,
      [
        opts.project ?? projectId,
        userId,
        label,
        `Revision ${label}`,
        opts.published ?? true,
        opts.visibility ?? "public",
        opts.updatedAt ?? day(2),
      ],
    );
    return res.rows[0].id;
  }

  async function listedAt(versionId: string): Promise<string | null> {
    const res = await client.query("SELECT mcp_listed_at FROM apiome.versions WHERE id = $1", [versionId]);
    const value = res.rows[0].mcp_listed_at as Date | null;
    return value ? value.toISOString().replace(".000Z", "Z") : null;
  }

  async function rollup(project = projectId): Promise<{ public: string | null; all: string | null } | null> {
    const res = await client.query(
      "SELECT public_listed_at, listed_at, tenant_id FROM apiome.mcp_project_listing WHERE project_id = $1",
      [project],
    );
    if (res.rowCount === 0) return null;
    const iso = (d: Date | null) => (d ? d.toISOString().replace(".000Z", "Z") : null);
    expect(res.rows[0].tenant_id).toBe(tenantId);
    return { public: iso(res.rows[0].public_listed_at), all: iso(res.rows[0].listed_at) };
  }

  /**
   * The invariants, over every revision of the test tenant: the stored value is the computed one,
   * a public revision's value is the view's, the view lists exactly the public listed revisions,
   * and each project's rollup is the aggregate of its revisions.
   */
  async function expectConsistent(): Promise<void> {
    const drift = await client.query(
      `SELECT v.id FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
        WHERE p.tenant_id = $1
          AND v.mcp_listed_at IS DISTINCT FROM apiome.compute_mcp_listed_at_for_version(v.id)`,
      [tenantId],
    );
    expect(drift.rows).toEqual([]);

    const view = await client.query(
      `SELECT v.id, s.id AS in_view, s.updated_at, v.mcp_listed_at, v.visibility
         FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
         LEFT JOIN apiome.mcp_v_public_specs s ON s.id = v.id
        WHERE p.tenant_id = $1`,
      [tenantId],
    );
    for (const row of view.rows) {
      const listedPublic = row.mcp_listed_at !== null && row.visibility === "public";
      expect(row.in_view !== null).toBe(listedPublic);
      if (row.in_view !== null) expect(row.updated_at).toEqual(row.mcp_listed_at);
    }

    const rollups = await client.query(
      `SELECT p.id,
              l.public_listed_at, l.listed_at,
              a.public_listed_at AS want_public, a.listed_at AS want_all
         FROM apiome.projects p
         LEFT JOIN apiome.mcp_project_listing l ON l.project_id = p.id
         LEFT JOIN LATERAL (
           SELECT max(v.mcp_listed_at) FILTER (WHERE v.visibility = 'public') AS public_listed_at,
                  max(v.mcp_listed_at) AS listed_at
             FROM apiome.versions v WHERE v.project_id = p.id
         ) a ON TRUE
        WHERE p.tenant_id = $1`,
      [tenantId],
    );
    for (const row of rollups.rows) {
      expect(row.public_listed_at).toEqual(row.want_public);
      expect(row.listed_at).toEqual(row.want_all);
    }
  }

  it("lists a published revision at the newest of its own and its project's timestamps", async () => {
    const older = await addVersion("1.0.0", { updatedAt: day(0) }); // older than the project (day 1)
    const newer = await addVersion("1.1.0", { updatedAt: day(5) });
    expect(await listedAt(older)).toBe(day(1));
    expect(await listedAt(newer)).toBe(day(5));
    expect(await rollup()).toEqual({ public: day(5), all: day(5) });
    await expectConsistent();
  });

  it("does not list a draft, and writes no rollup row for a project of drafts", async () => {
    const draft = await addVersion("0.1.0", { published: false });
    expect(await listedAt(draft)).toBeNull();
    expect(await rollup()).toBeNull();
    await expectConsistent();
  });

  it("lists a private revision, outside the public rollup", async () => {
    const pub = await addVersion("1.0.0", { updatedAt: day(3) });
    const priv = await addVersion("2.0.0", { visibility: "private", updatedAt: day(9) });
    expect(await listedAt(priv)).toBe(day(9));
    expect(await rollup()).toEqual({ public: day(3), all: day(9) });
    // The search document stays public-only (V101).
    const tsv = await client.query("SELECT id, mcp_public_doc_tsv IS NOT NULL AS has FROM apiome.versions WHERE id = ANY($1)", [
      [pub, priv],
    ]);
    expect(Object.fromEntries(tsv.rows.map((r) => [r.id, r.has]))).toEqual({ [pub]: true, [priv]: false });
    await expectConsistent();
  });

  it("follows a publish, an edit that names updated_at, and an unpublish", async () => {
    const id = await addVersion("1.0.0", { published: false });
    await client.query("UPDATE apiome.versions SET published = TRUE, updated_at = $2 WHERE id = $1", [id, day(4)]);
    expect(await listedAt(id)).toBe(day(4));
    await client.query("UPDATE apiome.versions SET mock_enabled = TRUE, updated_at = $2 WHERE id = $1", [id, day(6)]);
    expect(await listedAt(id)).toBe(day(6));
    expect(await rollup()).toEqual({ public: day(6), all: day(6) });
    await expectConsistent();
    await client.query("UPDATE apiome.versions SET published = FALSE, updated_at = $2 WHERE id = $1", [id, day(7)]);
    expect(await listedAt(id)).toBeNull();
    expect(await rollup()).toEqual({ public: null, all: null });
    await expectConsistent();
  });

  it("follows a visibility change", async () => {
    const id = await addVersion("1.0.0", { updatedAt: day(4) });
    await client.query("UPDATE apiome.versions SET visibility = 'private' WHERE id = $1", [id]);
    expect(await listedAt(id)).toBe(day(4));
    expect(await rollup()).toEqual({ public: null, all: day(4) });
    await expectConsistent();
  });

  it("follows the project: a touch, a rename, a disable and a restore", async () => {
    const pub = await addVersion("1.0.0", { updatedAt: day(2) });
    const draft = await addVersion("1.1.0", { published: false });
    await client.query("UPDATE apiome.projects SET description = 'x', updated_at = $2 WHERE id = $1", [projectId, day(8)]);
    expect(await listedAt(pub)).toBe(day(8));
    expect(await listedAt(draft)).toBeNull();
    expect(await rollup()).toEqual({ public: day(8), all: day(8) });
    await expectConsistent();

    await client.query("UPDATE apiome.projects SET name = 'Billing', updated_at = $2 WHERE id = $1", [projectId, day(9)]);
    const doc = await client.query(
      "SELECT mcp_public_doc_tsv @@ plainto_tsquery('english', 'billing') AS hit FROM apiome.versions WHERE id = $1",
      [pub],
    );
    expect(doc.rows[0].hit).toBe(true);
    expect(await listedAt(pub)).toBe(day(9));
    await expectConsistent();

    await client.query("UPDATE apiome.projects SET enabled = FALSE, updated_at = $2 WHERE id = $1", [projectId, day(10)]);
    expect(await listedAt(pub)).toBeNull();
    expect(await rollup()).toEqual({ public: null, all: null });
    await expectConsistent();

    await client.query("UPDATE apiome.projects SET enabled = TRUE, updated_at = $2 WHERE id = $1", [projectId, day(11)]);
    expect(await listedAt(pub)).toBe(day(11));
    await expectConsistent();
  });

  it("follows tags: added, edited, moved to another revision, deleted", async () => {
    const first = await addVersion("1.0.0", { updatedAt: day(2) });
    const second = await addVersion("1.1.0", { updatedAt: day(3) });
    const tag = (
      await client.query(
        "INSERT INTO apiome.version_tags (project_id, version_id, name, updated_at) VALUES ($1, $2, 'stable', $3) RETURNING id",
        [projectId, first, day(20)],
      )
    ).rows[0].id;
    expect(await listedAt(first)).toBe(day(20));
    expect(await rollup()).toEqual({ public: day(20), all: day(20) });
    await expectConsistent();

    await client.query("UPDATE apiome.version_tags SET message = 'm', updated_at = $2 WHERE id = $1", [tag, day(21)]);
    expect(await listedAt(first)).toBe(day(21));
    await expectConsistent();

    // Moved: the revision it left falls back to its own timestamp and loses the tag's name.
    await client.query("UPDATE apiome.version_tags SET version_id = $2, updated_at = $3 WHERE id = $1", [
      tag,
      second,
      day(22),
    ]);
    expect(await listedAt(first)).toBe(day(2));
    expect(await listedAt(second)).toBe(day(22));
    const docs = await client.query(
      "SELECT id, mcp_public_doc_tsv @@ plainto_tsquery('english', 'stable') AS hit FROM apiome.versions WHERE id = ANY($1)",
      [[first, second]],
    );
    expect(Object.fromEntries(docs.rows.map((r) => [r.id, r.hit]))).toEqual({ [first]: false, [second]: true });
    await expectConsistent();

    await client.query("DELETE FROM apiome.version_tags WHERE id = $1", [tag]);
    expect(await listedAt(second)).toBe(day(3));
    expect(await rollup()).toEqual({ public: day(3), all: day(3) });
    await expectConsistent();
  });

  it("follows a soft delete and a hard delete of a revision", async () => {
    const keep = await addVersion("1.0.0", { updatedAt: day(2) });
    const soft = await addVersion("1.1.0", { updatedAt: day(6) });
    const hard = await addVersion("1.2.0", { updatedAt: day(9) });
    expect(await rollup()).toEqual({ public: day(9), all: day(9) });
    await client.query("DELETE FROM apiome.versions WHERE id = $1", [hard]);
    expect(await rollup()).toEqual({ public: day(6), all: day(6) });
    await client.query("UPDATE apiome.versions SET deleted_at = now() WHERE id = $1", [soft]);
    expect(await listedAt(soft)).toBeNull();
    expect(await rollup()).toEqual({ public: day(2), all: day(2) });
    expect(await listedAt(keep)).toBe(day(2));
    await expectConsistent();
  });

  it("moves a revision's rollup when it changes project", async () => {
    const other = await addProject("Orders", day(1));
    const id = await addVersion("1.0.0", { updatedAt: day(5) });
    await client.query("UPDATE apiome.versions SET project_id = $2 WHERE id = $1", [id, other]);
    expect(await rollup()).toEqual({ public: null, all: null });
    expect(await rollup(other)).toEqual({ public: day(5), all: day(5) });
    await expectConsistent();
  });

  it("removes the rollup with its project", async () => {
    const other = await addProject("Orders", day(1));
    await addVersion("1.0.0", { project: other });
    expect(await rollup(other)).not.toBeNull();
    await client.query("DELETE FROM apiome.projects WHERE id = $1", [other]);
    const left = await client.query("SELECT 1 FROM apiome.mcp_project_listing WHERE project_id = $1", [other]);
    expect(left.rowCount).toBe(0);
  });

  it("does not count listing maintenance as a content change", async () => {
    const id = await addVersion("1.0.0", { updatedAt: day(2) });
    const stamp = async () =>
      (await client.query("SELECT content_stamp FROM apiome.versions WHERE id = $1", [id])).rows[0].content_stamp;
    const before = await stamp();
    await client.query("UPDATE apiome.projects SET updated_at = $2 WHERE id = $1", [projectId, day(12)]);
    await client.query("INSERT INTO apiome.version_tags (project_id, version_id, name) VALUES ($1, $2, 'lts')", [
      projectId,
      id,
    ]);
    expect(await listedAt(id)).not.toBe(day(2));
    expect(await stamp()).toBe(before);
  });

  it("leaves a revision untouched when nothing it derives changes", async () => {
    const id = await addVersion("0.1.0", { published: false });
    const xmin = async () => (await client.query("SELECT xmin::text, ctid::text FROM apiome.versions WHERE id = $1", [id])).rows[0];
    const before = await xmin();
    // A draft's search document and timestamp stay NULL: the trigger's refresh writes nothing.
    await client.query("UPDATE apiome.projects SET updated_at = $2 WHERE id = $1", [projectId, day(30)]);
    await client.query("UPDATE apiome.projects SET name = 'Renamed' WHERE id = $1", [projectId]);
    expect(await xmin()).toEqual(before);
  });

  it("serves a listing page from the public index", async () => {
    // The test database is nearly empty, where any plan is as cheap as another: rule out the
    // plans that do not need the index, and check that the index can then answer the page in order.
    await client.query("SET LOCAL enable_seqscan = off");
    await client.query("SET LOCAL enable_bitmapscan = off");
    await client.query("SET LOCAL enable_sort = off");
    const plan = await client.query(
      `EXPLAIN (FORMAT JSON)
       SELECT v.id FROM apiome.versions v
        WHERE v.mcp_listed_at IS NOT NULL AND v.visibility = 'public'::apiome.visibility_type
        ORDER BY v.mcp_listed_at DESC, v.id DESC LIMIT 51`,
    );
    const text = JSON.stringify(plan.rows[0]["QUERY PLAN"]);
    expect(text).toContain("idx_versions_mcp_public_listed");
    expect(text).not.toContain('"Node Type":"Sort"');
  });
});
