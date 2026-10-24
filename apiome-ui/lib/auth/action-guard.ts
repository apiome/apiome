/**
 * Checks that every server action runs before it touches data.
 *
 * Every export of a `'use server'` module is a public POST endpoint: anyone holding the action id
 * can call it with any arguments, and `src/middleware.ts` authenticates nothing. So the action
 * modules (`lib/db/helper-actions.ts`, `lib/db/admin-actions.ts`, `lib/db/import-actions.ts`) open
 * every action with one of these checks, and the data libraries they delegate to are no longer
 * `'use server'` at all (`tests/server-action-surface.test.ts` pins that).
 *
 * Each check resolves to `null` when the caller may proceed, or to the refusal message the action
 * returns. The rules:
 *
 * - **Who the caller is comes from the session**, never from an argument. An action that takes a
 *   user id only accepts the caller's own ({@link requireSelf}).
 * - **A resource outside the caller's workspaces is "not found"** — the same answer as a missing one,
 *   so a refusal does not confirm that an id exists ({@link requireTenantMember}).
 * - **Role grants come from apiome-rest** (`GET /v1/access/{tenant}/permissions/me`), the same
 *   evaluation every REST route enforces, and a check fails closed when REST cannot answer
 *   ({@link requireTenantPermission}).
 * - **The admin console needs the super-admin cookie** ({@link requireSuperAdmin}).
 *
 * Deliberately **not** a `'use server'` module: these functions are not callable from the client.
 */

import { cookies } from 'next/headers';

import { verifyAdminSessionToken } from './admin-session';
// Spelled `../auth/server-session` (not `./`) so the jest `auth/server-session` mock mapping applies.
import { getAuthSession } from '../auth/server-session';
import { createRestAuthHeaders, REST_API_BASE_URL } from '../rest-auth';

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('../db/db');

/** A check's verdict: `null` to proceed, or the refusal message. */
export type Refusal = string | null;

/** Said when nobody is signed in. */
export const UNAUTHORIZED = 'Unauthorized';

/** Said for a missing resource and one outside the caller's workspaces alike. */
export const NOT_FOUND = 'Not found';

/**
 * The refusal for a missing role grant.
 *
 * @param permission The `resource:action` permission that was missing.
 * @returns A sentence that names the permission.
 */
export function forbidden(permission: string): string {
  return `You do not have permission to do that in this workspace (${permission}).`;
}

/** The signed-in caller, as the session describes them. */
export interface ActionCaller {
  userId: string;
  /** The workspace selected in the session, if any. */
  tenantId: string | null;
  email?: string | null;
  name?: string | null;
}

/**
 * Read the signed-in caller from the session.
 *
 * @returns The caller, or `null` when nobody is signed in (or the session cannot be read).
 */
export async function getActionCaller(): Promise<ActionCaller | null> {
  const session = await getAuthSession().catch(() => null);
  const user = session?.user as
    | { user_id?: string; current_tenant_id?: string; email?: string | null; name?: string | null }
    | undefined;
  if (!user?.user_id) return null;
  return { userId: user.user_id, tenantId: user.current_tenant_id ?? null, email: user.email, name: user.name };
}

/**
 * Require a signed-in caller.
 *
 * @returns `null`, or {@link UNAUTHORIZED}.
 */
export async function requireSignedIn(): Promise<Refusal> {
  return (await getActionCaller()) ? null : UNAUTHORIZED;
}

/**
 * Require that `userId` is the signed-in caller — for actions on a user's own account.
 *
 * @param userId The user the action is about.
 * @returns `null`, or {@link UNAUTHORIZED}.
 */
export async function requireSelf(userId: unknown): Promise<Refusal> {
  const caller = await getActionCaller();
  if (!caller || typeof userId !== 'string' || userId !== caller.userId) return UNAUTHORIZED;
  return null;
}

/**
 * Like {@link requireSelf}, but an absent user (`undefined` / `null`) is allowed — for reads that
 * take an optional "and this user's personal copy" argument. A signed-in caller is still required.
 *
 * @param userId The optional user the action is about.
 * @returns `null`, or {@link UNAUTHORIZED}.
 */
export async function requireSelfOrNobody(userId: unknown): Promise<Refusal> {
  if (userId === undefined || userId === null) return requireSignedIn();
  return requireSelf(userId);
}

/**
 * Require that the caller belongs to the workspace (as a member or a tenant administrator).
 *
 * @param tenantId The workspace, or `null` when the resource it was resolved from does not exist.
 * @returns `null`; {@link UNAUTHORIZED} when signed out; {@link NOT_FOUND} otherwise.
 */
export async function requireTenantMember(tenantId: string | null | undefined): Promise<Refusal> {
  const caller = await getActionCaller();
  if (!caller) return UNAUTHORIZED;
  if (!tenantId) return NOT_FOUND;
  const result = await connectionPool.query(
    `SELECT 1 FROM apiome.tenant_users WHERE tenant_id = $1 AND user_id = $2
     UNION ALL
     SELECT 1 FROM apiome.tenant_administrators WHERE tenant_id = $1 AND user_id = $2
     LIMIT 1`,
    [tenantId, caller.userId]
  );
  return result.rows.length > 0 ? null : NOT_FOUND;
}

/**
 * Require that the caller is a tenant administrator of the workspace — for workspace settings and
 * membership, which the app reserves to administrators.
 *
 * @param tenantId The workspace, or `null` when it could not be resolved.
 * @returns `null`; {@link UNAUTHORIZED} when signed out; {@link NOT_FOUND} for a workspace the caller
 *   is not in; a refusal naming `tenant:admin` for a member who is not an administrator.
 */
export async function requireTenantAdmin(tenantId: string | null | undefined): Promise<Refusal> {
  const membership = await requireTenantMember(tenantId);
  if (membership) return membership;
  const caller = (await getActionCaller()) as ActionCaller;
  const result = await connectionPool.query(
    'SELECT 1 FROM apiome.tenant_administrators WHERE tenant_id = $1 AND user_id = $2 LIMIT 1',
    [tenantId, caller.userId]
  );
  return result.rows.length > 0 ? null : forbidden('tenant:admin');
}

/** apiome-rest's answer to `GET /v1/access/{tenant}/permissions/me`. */
export interface TenantGrants {
  is_admin?: boolean;
  permissions?: string[];
}

/**
 * Read the caller's grants in a workspace from apiome-rest. REST checks membership itself.
 *
 * @param caller The signed-in caller.
 * @param tenantId The workspace.
 * @param tenantSlug The workspace's slug.
 * @returns The grants, or `null` when REST refused or could not answer.
 */
export async function fetchTenantGrants(
  caller: Pick<ActionCaller, 'userId' | 'email' | 'name'>,
  tenantId: string,
  tenantSlug: string
): Promise<TenantGrants | null> {
  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/access/${encodeURIComponent(tenantSlug)}/permissions/me`,
      {
        headers: createRestAuthHeaders({
          user_id: caller.userId,
          email: caller.email,
          name: caller.name,
          current_tenant_id: tenantId,
        }),
        cache: 'no-store',
      }
    );
    if (!response.ok) return null;
    return (await response.json()) as TenantGrants;
  } catch {
    return null;
  }
}

/**
 * Whether a grant set allows a permission (tenant administrators hold every permission).
 *
 * @param grants The caller's grants, or `null` when unknown.
 * @param permission The `resource:action` permission.
 * @returns `true` only for a known grant.
 */
export function grantsAllow(grants: TenantGrants | null, permission: string): boolean {
  return grants !== null && (grants.is_admin === true || (grants.permissions ?? []).includes(permission));
}

/**
 * Require a role grant in the workspace, as apiome-rest evaluates it.
 *
 * @param tenantId The workspace, or `null` when the resource it was resolved from does not exist.
 * @param permission The `resource:action` permission, e.g. `api_keys:delete`.
 * @returns `null`; {@link UNAUTHORIZED} / {@link NOT_FOUND} as {@link requireTenantMember}; otherwise
 *   {@link forbidden} — also when REST cannot answer.
 */
export async function requireTenantPermission(
  tenantId: string | null | undefined,
  permission: string
): Promise<Refusal> {
  const membership = await requireTenantMember(tenantId);
  if (membership) return membership;
  const caller = (await getActionCaller()) as ActionCaller;
  const tenant = await connectionPool.query(
    'SELECT slug FROM apiome.tenants WHERE id = $1 AND deleted_at IS NULL',
    [tenantId]
  );
  const slug = tenant.rows[0]?.slug;
  if (!slug) return NOT_FOUND;
  const grants = await fetchTenantGrants(caller, tenantId as string, slug);
  return grantsAllow(grants, permission) ? null : forbidden(permission);
}

/**
 * Require the super-admin session the admin console signs in with (the `admin_session` cookie).
 *
 * @returns `null`, or {@link UNAUTHORIZED}.
 */
export async function requireSuperAdmin(): Promise<Refusal> {
  try {
    const store = await cookies();
    return verifyAdminSessionToken(store.get('admin_session')?.value) ? null : UNAUTHORIZED;
  } catch {
    return UNAUTHORIZED;
  }
}

// ---------------------------------------------------------------------------
// Which workspace a resource belongs to. Each returns `null` for a missing id.
// ---------------------------------------------------------------------------

/**
 * Run a one-column tenant lookup.
 *
 * @param sql A query selecting `tenant_id` for the parameter.
 * @param id The resource id.
 * @returns The tenant id, or `null`.
 */
async function lookupTenant(sql: string, id: unknown): Promise<string | null> {
  if (typeof id !== 'string' || !id) return null;
  try {
    const result = await connectionPool.query(sql, [id]);
    const tenantId = result.rows[0]?.tenant_id;
    return tenantId ? String(tenantId) : null;
  } catch {
    // A malformed id (not a uuid) is a missing resource, not a server error.
    return null;
  }
}

/** The workspace a project belongs to. */
export function tenantOfProject(projectId: unknown): Promise<string | null> {
  return lookupTenant('SELECT tenant_id FROM apiome.projects WHERE id = $1', projectId);
}

/** The workspace a version (by record id) belongs to. */
export function tenantOfVersion(versionRecordId: unknown): Promise<string | null> {
  return lookupTenant(
    `SELECT p.tenant_id FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id WHERE v.id = $1`,
    versionRecordId
  );
}

/**
 * The workspace and project a version (by record id) belongs to.
 *
 * @param versionRecordId The version's record id.
 * @returns Both ids, or `null` for a missing version.
 */
export async function versionScope(
  versionRecordId: unknown
): Promise<{ tenantId: string; projectId: string } | null> {
  if (typeof versionRecordId !== 'string' || !versionRecordId) return null;
  try {
    const result = await connectionPool.query(
      `SELECT p.tenant_id, v.project_id FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.id = $1`,
      [versionRecordId]
    );
    const row = result.rows[0];
    return row ? { tenantId: String(row.tenant_id), projectId: String(row.project_id) } : null;
  } catch {
    return null;
  }
}

/** The workspace a class belongs to. */
export function tenantOfClass(classId: unknown): Promise<string | null> {
  return lookupTenant(
    `SELECT p.tenant_id FROM apiome.classes c
       JOIN apiome.versions v ON v.id = c.version_id
       JOIN apiome.projects p ON p.id = v.project_id
      WHERE c.id = $1`,
    classId
  );
}

/** The workspace an API key belongs to. */
export function tenantOfApiKey(apiKeyId: unknown): Promise<string | null> {
  return lookupTenant('SELECT tenant_id FROM apiome.api_keys WHERE id = $1', apiKeyId);
}

/** The workspace a `tenant_administrators` row belongs to. */
export function tenantOfAdministratorRecord(recordId: unknown): Promise<string | null> {
  return lookupTenant('SELECT tenant_id FROM apiome.tenant_administrators WHERE id = $1', recordId);
}

/** The workspace a `tenant_users` row belongs to. */
export function tenantOfMemberRecord(recordId: unknown): Promise<string | null> {
  return lookupTenant('SELECT tenant_id FROM apiome.tenant_users WHERE id = $1', recordId);
}

/**
 * The single workspace a set of classes belongs to.
 *
 * @param classIds The class ids.
 * @returns The workspace, or `null` when any class is missing or they span workspaces.
 */
export async function tenantOfClasses(classIds: unknown): Promise<string | null> {
  if (!Array.isArray(classIds) || classIds.some((id) => typeof id !== 'string')) return null;
  if (classIds.length === 0) return null;
  try {
    const result = await connectionPool.query(
      `SELECT DISTINCT p.tenant_id, COUNT(DISTINCT c.id) OVER () AS found
         FROM apiome.classes c
         JOIN apiome.versions v ON v.id = c.version_id
         JOIN apiome.projects p ON p.id = v.project_id
        WHERE c.id = ANY($1::uuid[])`,
      [classIds]
    );
    const unique = new Set(classIds);
    if (result.rows.length !== 1 || Number(result.rows[0].found) !== unique.size) return null;
    return String(result.rows[0].tenant_id);
  } catch {
    return null;
  }
}
