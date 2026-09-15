/**
 * Seed data for the COL-2.2 review page journey (#4518).
 *
 * A review page needs state the UI cannot create on its own yet (requesting a review has no screen
 * until later COL tickets): a tenant with a requester and a reviewer, a project with a published
 * baseline and two draft versions, and a review of each draft. Users, tenant, roles, project and
 * versions are written to Postgres directly; the **reviews are requested through apiome-rest** as the
 * requester, so each round's spec fingerprint is the one apiome-rest computes — a review seeded by
 * SQL would refuse every decision as `review-spec-changed`.
 *
 * Everything carries a per-run suffix, so re-runs against a shared stack never collide.
 */
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';
import { databaseUrl, journeyServerEnv, restApiBaseUrl } from './env';
import { seedCredentialUser, seedVerifiedUser } from './db';

/** A seeded revision. */
export interface SeededVersion {
  id: string;
  label: string;
}

/** What {@link seedReviewFixture} created. */
export interface ReviewFixture {
  tenantId: string;
  tenantSlug: string;
  projectId: string;
  /** Asks for the reviews; never signs in. */
  requester: { id: string; email: string; name: string };
  /** Signs in through the credentials form and decides. */
  reviewer: { id: string; email: string; password: string; name: string };
  /** The published version the drafts are compared with. */
  baseline: SeededVersion;
  /** The draft the approve journey decides on. */
  approveDraft: SeededVersion;
  /** The draft the request-changes journey decides on. */
  changesDraft: SeededVersion;
}

let pool: Pool | null = null;

/** Lazily open this fixture's connection pool. */
function getPool(): Pool {
  if (!pool) {
    pool = new Pool({ connectionString: databaseUrl(), max: 2 });
  }
  return pool;
}

/** Close the pool. Call from `test.afterAll`. */
export async function closeReviewFixtureDb(): Promise<void> {
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
    `INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES ($1, $2)
     ON CONFLICT (tenant_id, user_id) DO NOTHING`,
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
 * Insert a version with one class per name.
 *
 * @param projectId - The project.
 * @param creatorId - Its creator.
 * @param label - The version label.
 * @param classNames - The classes it holds.
 * @param published - Whether it is published.
 * @returns The version.
 */
async function addVersion(
  projectId: string,
  creatorId: string,
  label: string,
  classNames: readonly string[],
  published: boolean
): Promise<SeededVersion> {
  const db = getPool();
  const result = await db.query(
    `INSERT INTO apiome.versions (project_id, creator_id, version_id, published, published_at)
     VALUES ($1, $2, $3, $4, CASE WHEN $4 THEN CURRENT_TIMESTAMP END)
     RETURNING id`,
    [projectId, creatorId, label, published]
  );
  const id = result.rows[0].id as string;
  for (const name of classNames) {
    await db.query(`INSERT INTO apiome.classes (version_id, name, schema) VALUES ($1, $2, $3::jsonb)`, [
      id,
      name,
      JSON.stringify({ type: 'object', properties: { id: { type: 'string' } } }),
    ]);
  }
  return { id, label };
}

/**
 * Seed a tenant, its requester and reviewer, and a project with a published baseline and two drafts.
 *
 * @param runId - The per-run suffix.
 * @returns The fixture.
 */
export async function seedReviewFixture(runId: number = Date.now()): Promise<ReviewFixture> {
  const db = getPool();
  const tenantSlug = `col22-review-${runId}`;
  const tenant = await db.query(
    `INSERT INTO apiome.tenants (name, slug, description, enabled) VALUES ($1, $2, $3, true) RETURNING id`,
    [`Review journey ${runId}`, tenantSlug, 'COL-2.2 review page journey']
  );
  const tenantId = tenant.rows[0].id as string;
  await db.query('SELECT apiome.seed_builtin_roles($1)', [tenantId]);

  const requester = { email: `col22-requester-${runId}@example.com`, name: 'Rae Requester' };
  const requesterId = await seedVerifiedUser(requester.email, requester.name);
  const reviewer = {
    email: `col22-reviewer-${runId}@example.com`,
    password: `Review-${runId}-journey!`,
    name: 'Ravi Reviewer',
  };
  const reviewerId = await seedCredentialUser(reviewer.email, reviewer.password, reviewer.name);
  await addMember(tenantId, requesterId, 'editor');
  await addMember(tenantId, reviewerId, 'viewer');

  const project = await db.query(
    `INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES ($1, $2, $3, $4) RETURNING id`,
    [tenantId, requesterId, 'Review Journey Pets', `pets-${runId}`]
  );
  const projectId = project.rows[0].id as string;

  const baseline = await addVersion(projectId, requesterId, '1.0.0', ['Pet'], true);
  const approveDraft = await addVersion(projectId, requesterId, '2.0.0', ['Pet', 'Owner'], false);
  const changesDraft = await addVersion(projectId, requesterId, '2.1.0', ['Owner'], false);

  return {
    tenantId,
    tenantSlug,
    projectId,
    requester: { id: requesterId, ...requester },
    reviewer: { id: reviewerId, ...reviewer },
    baseline,
    approveDraft,
    changesDraft,
  };
}

/**
 * Headers for apiome-rest as the requester — signed exactly as the app's BFF signs its tokens.
 *
 * @param fixture - The fixture.
 * @returns The headers.
 */
function requesterHeaders(fixture: ReviewFixture): Record<string, string> {
  const secret = journeyServerEnv().BETTER_AUTH_SECRET;
  const token = jwt.sign(
    {
      user_id: fixture.requester.id,
      sub: fixture.requester.id,
      email: fixture.requester.email,
      name: fixture.requester.name,
      current_tenant_id: fixture.tenantId,
    },
    secret,
    { algorithm: 'HS256', expiresIn: '1h' }
  );
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

/**
 * Ask the reviewer to review a draft, through apiome-rest.
 *
 * @param fixture - The fixture.
 * @param version - The draft.
 * @returns The new review's id.
 */
export async function requestReview(fixture: ReviewFixture, version: SeededVersion): Promise<string> {
  const response = await fetch(
    `${restApiBaseUrl()}/tenants/${fixture.tenantSlug}/projects/${fixture.projectId}/reviews`,
    {
      method: 'POST',
      headers: requesterHeaders(fixture),
      body: JSON.stringify({ version: version.id, reviewers: [fixture.reviewer.id] }),
    }
  );
  if (!response.ok) {
    throw new Error(`requesting a review failed (${response.status}): ${await response.text()}`);
  }
  const body = (await response.json()) as { review: { id: string } };
  return body.review.id;
}

/**
 * Read a review back from apiome-rest, to prove what the page recorded.
 *
 * @param fixture - The fixture.
 * @param reviewId - The review.
 * @returns The review detail.
 */
export async function readReview(
  fixture: ReviewFixture,
  reviewId: string
): Promise<{ review: { state: string }; reviewers: Array<{ decision: string; note: string | null }> }> {
  const response = await fetch(
    `${restApiBaseUrl()}/tenants/${fixture.tenantSlug}/projects/${fixture.projectId}/reviews/${reviewId}`,
    { headers: requesterHeaders(fixture) }
  );
  if (!response.ok) {
    throw new Error(`reading the review failed (${response.status}): ${await response.text()}`);
  }
  return response.json();
}
