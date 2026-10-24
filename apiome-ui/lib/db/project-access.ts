/**
 * Authorize a project write made from a server action.
 *
 * `lib/db/helper.ts` is a `'use server'` module, so every function it exports is a server action:
 * a public POST endpoint that any caller holding the action id (it ships in the client bundle) can
 * invoke with any arguments. Before this guard, `updateProject`, `deleteProject`, `restoreProject`
 * and `permanentDeleteProject` wrote by project id alone — no session, no tenant scoping, no
 * permission — and `createProject` trusted a tenant id sent by the client. Nothing in front of them
 * (`src/middleware.ts` authenticates nothing) stopped an anonymous or cross-tenant call.
 *
 * {@link authorizeProjectAction} closes that:
 *
 * 1. **A session is required**, and the tenant is the session's current tenant — never a value the
 *    caller supplies.
 * 2. **The project must belong to that tenant.** A project in another tenant is reported as not
 *    found, so the answer does not confirm that the id exists.
 * 3. **The caller must hold `projects:<action>`** in that tenant. The grant comes from apiome-rest's
 *    `GET /v1/access/{tenant}/permissions/me` — the same evaluation every REST route enforces
 *    (tenant administrators pass; otherwise the member's role grid) — so the role rules live in one
 *    place. If REST cannot answer, the write is refused (fail closed).
 *
 * Deliberately **not** a `'use server'` module: these functions are not callable from the client.
 */

import { getAuthSession } from '../auth/server-session';
import { createRestAuthHeaders, REST_API_BASE_URL } from '../rest-auth';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** The project actions a server action may perform. */
export type ProjectAction = 'create' | 'edit' | 'delete';

/** A caller allowed to perform the action: who they are and the tenant it is scoped to. */
export interface AuthorizedProjectCaller {
  ok: true;
  userId: string;
  tenantId: string;
}

/** A refused action, with the message the server action returns. */
export interface RefusedProjectCaller {
  ok: false;
  error: string;
}

/** Said for a missing or out-of-tenant project alike, so the answer leaks nothing. */
export const PROJECT_NOT_FOUND = 'Project not found';

/** Said when the caller is not signed in, or has no workspace selected. */
export const PROJECT_UNAUTHORIZED = 'Unauthorized';

/**
 * The refusal for a missing grant.
 *
 * @param action The action that was refused.
 * @returns A sentence that names the permission.
 */
export function projectForbidden(action: ProjectAction): string {
  return `You do not have permission to ${action} projects in this workspace (projects:${action}).`;
}

/** apiome-rest's answer to `GET /v1/access/{tenant}/permissions/me`. */
interface MyPermissions {
  is_admin?: boolean;
  permissions?: string[];
}

/**
 * Read the caller's grants in the tenant from apiome-rest.
 *
 * @param user The session user, scoped to the tenant.
 * @param tenantSlug The tenant's slug.
 * @returns The grants, or `null` when REST could not answer.
 */
async function fetchMyPermissions(
  user: { user_id: string; email?: string | null; name?: string | null; current_tenant_id: string },
  tenantSlug: string
): Promise<MyPermissions | null> {
  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/access/${encodeURIComponent(tenantSlug)}/permissions/me`,
      { headers: createRestAuthHeaders(user), cache: 'no-store' }
    );
    if (!response.ok) return null;
    return (await response.json()) as MyPermissions;
  } catch {
    return null;
  }
}

/**
 * Decide whether the signed-in caller may perform `action` on projects — on one project when
 * `projectId` is given, in their current tenant otherwise.
 *
 * @param action The project action (`create`, `edit` or `delete`).
 * @param projectId The project acted on; omitted for `create`.
 * @returns The authorized caller, or the refusal to return.
 */
export async function authorizeProjectAction(
  action: ProjectAction,
  projectId?: string
): Promise<AuthorizedProjectCaller | RefusedProjectCaller> {
  const session = await getAuthSession();
  const user = session?.user as
    | { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string }
    | undefined;
  const userId = user?.user_id;
  const tenantId = user?.current_tenant_id;
  if (!userId || !tenantId) return { ok: false, error: PROJECT_UNAUTHORIZED };

  if (projectId !== undefined) {
    const owner = await connectionPool.query('SELECT tenant_id FROM apiome.projects WHERE id = $1', [projectId]);
    const projectTenant = owner.rows[0]?.tenant_id;
    if (!projectTenant || String(projectTenant) !== String(tenantId)) {
      return { ok: false, error: PROJECT_NOT_FOUND };
    }
  }

  const tenant = await connectionPool.query(
    'SELECT slug FROM apiome.tenants WHERE id = $1 AND deleted_at IS NULL',
    [tenantId]
  );
  const tenantSlug = tenant.rows[0]?.slug;
  if (!tenantSlug) return { ok: false, error: PROJECT_UNAUTHORIZED };

  const grants = await fetchMyPermissions(
    { user_id: userId, email: user?.email, name: user?.name, current_tenant_id: tenantId },
    tenantSlug
  );
  const allowed =
    grants !== null &&
    (grants.is_admin === true || (grants.permissions ?? []).includes(`projects:${action}`));
  if (!allowed) return { ok: false, error: projectForbidden(action) };

  return { ok: true, userId, tenantId };
}
