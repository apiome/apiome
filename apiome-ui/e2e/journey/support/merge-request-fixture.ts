/**
 * Seed data for the COL-4.3 merge request journey (#4527).
 *
 * A tenant with an author (who signs in and merges) and a reviewer (who signs in and approves), and
 * a project whose default branch `main` points at a draft version `1.0.0` holding a `Pet` class.
 * Users, tenant, roles, project, version and branch are written to Postgres directly; the **draft
 * branch and the merge request are created through apiome-rest** as the author — the Versions
 * screen's Merge requests tab is behind `FEATURE_GITLIKE` — so the review's spec fingerprint is the
 * one apiome-rest computes.
 *
 * Everything carries a per-run suffix, so re-runs against a shared stack never collide.
 */
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';
import { databaseUrl, journeyServerEnv, restApiBaseUrl } from './env';
import { seedCredentialUser } from './db';

/** A user who signs in through the credentials form. */
export interface JourneyUser {
  id: string;
  email: string;
  password: string;
  name: string;
}

/** What {@link seedMergeRequestFixture} created. */
export interface MergeRequestFixture {
  tenantId: string;
  tenantSlug: string;
  projectId: string;
  author: JourneyUser;
  reviewer: JourneyUser;
  /** The `main` branch and its tip before the merge. */
  main: { id: string; tipId: string };
}

let pool: Pool | null = null;

/** Lazily open this fixture's connection pool. */
function getPool(): Pool {
  if (!pool) pool = new Pool({ connectionString: databaseUrl(), max: 2 });
  return pool;
}

/** Close the pool. Call from `test.afterAll`. */
export async function closeMergeRequestFixtureDb(): Promise<void> {
  await pool?.end();
  pool = null;
}

/**
 * Give a user a built-in role in a tenant.
 *
 * @param tenantId - The tenant.
 * @param userId - The user.
 * @param roleSlug - `editor`, `viewer`, …
 */
async function addMember(tenantId: string, userId: string, roleSlug: string): Promise<void> {
  const db = getPool();
  await db.query(
    `INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES ($1, $2) ON CONFLICT (tenant_id, user_id) DO NOTHING`,
    [tenantId, userId]
  );
  await db.query(
    `INSERT INTO apiome.tenant_user_roles (tenant_id, user_id, role_id)
     SELECT r.tenant_id, $2, r.id FROM apiome.roles r WHERE r.tenant_id = $1 AND r.slug = $3
     ON CONFLICT (tenant_id, user_id) DO NOTHING`,
    [tenantId, userId, roleSlug]
  );
}

/**
 * Seed the tenant, its two users, and the project with `main` at a draft `1.0.0`.
 *
 * @param runId - The per-run suffix.
 * @returns The fixture.
 */
export async function seedMergeRequestFixture(runId: number = Date.now()): Promise<MergeRequestFixture> {
  const db = getPool();
  const tenantSlug = `col43-mr-${runId}`;
  const tenant = await db.query(
    `INSERT INTO apiome.tenants (name, slug, description, enabled) VALUES ($1, $2, $3, true) RETURNING id`,
    [`Merge request journey ${runId}`, tenantSlug, 'COL-4.3 merge request journey']
  );
  const tenantId = tenant.rows[0].id as string;
  await db.query('SELECT apiome.seed_builtin_roles($1)', [tenantId]);

  const author = { email: `col43-author-${runId}@example.com`, password: `Author-${runId}-journey!`, name: 'Ada Author' };
  const reviewer = { email: `col43-reviewer-${runId}@example.com`, password: `Review-${runId}-journey!`, name: 'Ravi Reviewer' };
  const authorId = await seedCredentialUser(author.email, author.password, author.name);
  const reviewerId = await seedCredentialUser(reviewer.email, reviewer.password, reviewer.name);
  await addMember(tenantId, authorId, 'editor');
  await addMember(tenantId, reviewerId, 'viewer');

  const project = await db.query(
    `INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES ($1, $2, $3, $4) RETURNING id`,
    [tenantId, authorId, 'Merge Journey Pets', `mr-pets-${runId}`]
  );
  const projectId = project.rows[0].id as string;
  const version = await db.query(
    `INSERT INTO apiome.versions (project_id, creator_id, version_id) VALUES ($1, $2, '1.0.0') RETURNING id`,
    [projectId, authorId]
  );
  const tipId = version.rows[0].id as string;
  await db.query(`INSERT INTO apiome.classes (version_id, name, schema) VALUES ($1, 'Pet', $2::jsonb)`, [
    tipId,
    JSON.stringify({ type: 'object' }),
  ]);
  const main = await db.query(
    `INSERT INTO apiome.version_branches (project_id, name, tip_version_id, is_default, branched_from_revision_id)
     VALUES ($1, 'main', $2, true, $2) RETURNING id`,
    [projectId, tipId]
  );

  return {
    tenantId,
    tenantSlug,
    projectId,
    author: { id: authorId, ...author },
    reviewer: { id: reviewerId, ...reviewer },
    main: { id: main.rows[0].id as string, tipId },
  };
}

/**
 * Headers for apiome-rest as the author — signed exactly as the app's BFF signs its tokens.
 *
 * @param fixture - The fixture.
 * @returns The headers.
 */
function authorHeaders(fixture: MergeRequestFixture): Record<string, string> {
  const token = jwt.sign(
    {
      user_id: fixture.author.id,
      sub: fixture.author.id,
      email: fixture.author.email,
      name: fixture.author.name,
      current_tenant_id: fixture.tenantId,
    },
    journeyServerEnv().BETTER_AUTH_SECRET,
    { algorithm: 'HS256', expiresIn: '1h' }
  );
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

/**
 * Call apiome-rest as the author and return its JSON, or throw with its reply.
 *
 * @param fixture - The fixture.
 * @param path - The path under the project, e.g. `/draft-branches`.
 * @param body - A JSON body for a POST; omit for a GET.
 * @returns The parsed reply.
 */
async function rest<T>(fixture: MergeRequestFixture, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${restApiBaseUrl()}/tenants/${fixture.tenantSlug}/projects/${fixture.projectId}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: authorHeaders(fixture),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} failed (${response.status}): ${await response.text()}`);
  return (await response.json()) as T;
}

/**
 * Draft a branch off `main`, add an `Owner` class to it, and open a merge request asking the reviewer.
 *
 * @param fixture - The fixture.
 * @returns The merge request id and the draft branch's tip.
 */
export async function openMergeRequest(fixture: MergeRequestFixture): Promise<{ id: string; tipId: string }> {
  const branch = await rest<{ tip_revision_id: string }>(fixture, '/draft-branches', {
    name: 'feature/owners',
    base_branch: 'main',
  });
  // The edit the branch carries — made before the review is requested, so its fingerprint covers it.
  await getPool().query(`INSERT INTO apiome.classes (version_id, name, schema) VALUES ($1, 'Owner', $2::jsonb)`, [
    branch.tip_revision_id,
    JSON.stringify({ type: 'object' }),
  ]);
  const detail = await rest<{ merge_request: { id: string } }>(fixture, '/merge-requests', {
    source_branch: 'feature/owners',
    title: 'Add owners',
    reviewers: [fixture.reviewer.id],
  });
  return { id: detail.merge_request.id, tipId: branch.tip_revision_id };
}

/**
 * Read a merge request back from apiome-rest, to prove what the page did.
 *
 * @param fixture - The fixture.
 * @param id - The merge request.
 * @returns Its state and the revision its merge produced.
 */
export async function readMergeRequest(
  fixture: MergeRequestFixture,
  id: string
): Promise<{ merge_request: { state: string; merged_version_id: string | null }; target_tip_revision_id: string | null }> {
  return rest(fixture, `/merge-requests/${id}`);
}
