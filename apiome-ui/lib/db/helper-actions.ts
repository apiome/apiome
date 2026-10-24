'use server';

/**
 * The workspace server actions client components call — and the only ones.
 *
 * `lib/db/helper.ts` used to be a `'use server'` module, which made each of its ~140 exports a public
 * endpoint taking whatever user, tenant or record id the caller sent. It is now a plain server
 * library; this module re-exposes just the functions the app's client components use, each behind a
 * check from `lib/auth/action-guard.ts`:
 *
 * | Check | Used for |
 * | --- | --- |
 * | `requireSelf(userId)` | the caller's own account, linked accounts and dashboard |
 * | `requireTenantMember(tenant)` | reading a workspace's members, versions, classes, layouts |
 * | `requireTenantAdmin(tenant)` | workspace settings and membership (Tenants page) |
 * | `requireTenantPermission(tenant, perm)` | role-gated writes, as REST enforces them |
 *
 * The project actions (`createProject` … `permanentDeleteProject`), `deleteVersion` and
 * `getCurrentUserLastLoginAt` check the session themselves and are passed through.
 *
 * A refusal is returned in each function's own result shape — `{ success: false, error }` as a JSON
 * string — so callers' existing error handling shows it. Adding an export here is a security
 * decision: `tests/server-action-surface.test.ts` lists every action and fails on a new one.
 */

import {
  requireSelf,
  requireSelfOrNobody,
  requireSignedIn,
  requireTenantAdmin,
  requireTenantMember,
  requireTenantPermission,
  NOT_FOUND,
  tenantOfAdministratorRecord,
  tenantOfApiKey,
  tenantOfClass,
  tenantOfClasses,
  tenantOfMemberRecord,
  tenantOfVersion,
  versionScope,
  type Refusal,
} from '../auth/action-guard';
import * as helper from './helper';

/**
 * The refusal in the helpers' result shape.
 *
 * @param error The refusal message.
 * @returns `{"success":false,"error":…}`.
 */
function refuse(error: string): string {
  return JSON.stringify({ success: false, error });
}

/**
 * Run `action` when `check` allowed it; otherwise return the refusal.
 *
 * @param check The guard's verdict.
 * @param action The helper call to make when allowed.
 * @returns The helper's result, or the refusal as JSON.
 */
async function guarded<T>(check: Promise<Refusal>, action: () => Promise<T>): Promise<T | string> {
  const refusal = await check;
  return refusal ? refuse(refusal) : action();
}

// ---- The caller's own account -------------------------------------------------------------------

export async function getDashboardStats(...args: Parameters<typeof helper.getDashboardStats>) {
  return guarded(requireSelf(args[0]), () => helper.getDashboardStats(...args));
}

export async function getRecentActivity(...args: Parameters<typeof helper.getRecentActivity>) {
  return guarded(requireSelf(args[0]), () => helper.getRecentActivity(...args));
}

export async function getTenantsForUser(...args: Parameters<typeof helper.getTenantsForUser>) {
  return guarded(requireSelf(args[0]), () => helper.getTenantsForUser(...args));
}

export async function getTenantsAdministratedByUser(
  ...args: Parameters<typeof helper.getTenantsAdministratedByUser>
) {
  return guarded(requireSelf(args[0]), () => helper.getTenantsAdministratedByUser(...args));
}

export async function updateUserName(...args: Parameters<typeof helper.updateUserName>) {
  return guarded(requireSelf(args[0]), () => helper.updateUserName(...args));
}

export async function updateUserPassword(...args: Parameters<typeof helper.updateUserPassword>) {
  return guarded(requireSelf(args[0]), () => helper.updateUserPassword(...args));
}

export async function getCurrentUserLastLoginAt() {
  return helper.getCurrentUserLastLoginAt();
}

export async function getLinkedAccountsForUser(...args: Parameters<typeof helper.getLinkedAccountsForUser>) {
  return guarded(requireSelf(args[0]), () => helper.getLinkedAccountsForUser(...args));
}

export async function getUserHasPassword(...args: Parameters<typeof helper.getUserHasPassword>) {
  return guarded(requireSelf(args[0]), () => helper.getUserHasPassword(...args));
}

export async function unlinkExternalAccount(...args: Parameters<typeof helper.unlinkExternalAccount>) {
  return guarded(requireSelf(args[0]), () => helper.unlinkExternalAccount(...args));
}

export async function updatePersonalAccessToken(...args: Parameters<typeof helper.updatePersonalAccessToken>) {
  return guarded(requireSelf(args[0]), () => helper.updatePersonalAccessToken(...args));
}

export async function removePersonalAccessToken(...args: Parameters<typeof helper.removePersonalAccessToken>) {
  return guarded(requireSelf(args[0]), () => helper.removePersonalAccessToken(...args));
}

// ---- Workspace settings and membership (Tenants page) -------------------------------------------

export async function getTenantUsers(...args: Parameters<typeof helper.getTenantUsers>) {
  return guarded(requireTenantMember(args[0]), () => helper.getTenantUsers(...args));
}

export async function updateTenant(...args: Parameters<typeof helper.updateTenant>) {
  return guarded(requireTenantAdmin(args[0]), () => helper.updateTenant(...args));
}

export async function addTenantAdministrator(...args: Parameters<typeof helper.addTenantAdministrator>) {
  return guarded(requireTenantAdmin(args[0]), () => helper.addTenantAdministrator(...args));
}

export async function addTenantUser(...args: Parameters<typeof helper.addTenantUser>) {
  return guarded(requireTenantAdmin(args[0]), () => helper.addTenantUser(...args));
}

export async function removeTenantAdministrator(...args: Parameters<typeof helper.removeTenantAdministrator>) {
  return guarded(
    tenantOfAdministratorRecord(args[0]).then(requireTenantAdmin),
    () => helper.removeTenantAdministrator(...args)
  );
}

export async function removeTenantUser(...args: Parameters<typeof helper.removeTenantUser>) {
  return guarded(tenantOfMemberRecord(args[0]).then(requireTenantAdmin), () => helper.removeTenantUser(...args));
}

// ---- Projects (each checks the session, tenant and projects:* grant itself) ---------------------

export async function createProject(...args: Parameters<typeof helper.createProject>) {
  return helper.createProject(...args);
}

export async function updateProject(...args: Parameters<typeof helper.updateProject>) {
  return helper.updateProject(...args);
}

export async function deleteProject(...args: Parameters<typeof helper.deleteProject>) {
  return helper.deleteProject(...args);
}

export async function restoreProject(...args: Parameters<typeof helper.restoreProject>) {
  return helper.restoreProject(...args);
}

export async function permanentDeleteProject(...args: Parameters<typeof helper.permanentDeleteProject>) {
  return helper.permanentDeleteProject(...args);
}

/**
 * Import an OpenAPI document as a new project. Creates a project, so it needs `projects:create`
 * in the target workspace, and the creator must be the caller.
 */
export async function importProjectFromOpenAPI(...args: Parameters<typeof helper.importProjectFromOpenAPI>) {
  const [tenantId, creatorId] = args;
  const check = requireSelf(creatorId).then(
    (refusal) => refusal ?? requireTenantPermission(tenantId, 'projects:create')
  );
  return guarded(check, () => helper.importProjectFromOpenAPI(...args));
}

// ---- Versions, classes and properties -----------------------------------------------------------

export async function getPublishedVersionsForTenant(
  ...args: Parameters<typeof helper.getPublishedVersionsForTenant>
) {
  return guarded(requireTenantMember(args[0]), () => helper.getPublishedVersionsForTenant(...args));
}

/** Public/private is part of publishing, so it needs `versions:publish`. */
export async function updateVersionVisibility(...args: Parameters<typeof helper.updateVersionVisibility>) {
  return guarded(
    tenantOfVersion(args[0]).then((tenant) => requireTenantPermission(tenant, 'versions:publish')),
    () => helper.updateVersionVisibility(...args)
  );
}

export async function deleteVersion(...args: Parameters<typeof helper.deleteVersion>) {
  return helper.deleteVersion(...args);
}

export async function getClassesForVersion(...args: Parameters<typeof helper.getClassesForVersion>) {
  return guarded(tenantOfVersion(args[0]).then(requireTenantMember), () => helper.getClassesForVersion(...args));
}

export async function getPropertiesForClass(...args: Parameters<typeof helper.getPropertiesForClass>) {
  return guarded(tenantOfClass(args[0]).then(requireTenantMember), () => helper.getPropertiesForClass(...args));
}

export async function getPropertiesForClassesBatch(
  ...args: Parameters<typeof helper.getPropertiesForClassesBatch>
) {
  const [classIds] = args;
  const check =
    Array.isArray(classIds) && classIds.length === 0
      ? requireSignedIn()
      : tenantOfClasses(classIds).then(requireTenantMember);
  return guarded(check, () => helper.getPropertiesForClassesBatch(...args));
}

/**
 * Build a version's OpenAPI document. The row comes from the caller, so the version must be in one
 * of the caller's workspaces and the row's project must be the version's own.
 *
 * @throws Error when the caller may not read the version (this returns the document, not JSON).
 */
export async function buildOpenApiSpecJsonForVersion(
  ...args: Parameters<typeof helper.buildOpenApiSpecJsonForVersion>
) {
  const [versionRow] = args;
  const scope = await versionScope(versionRow?.id);
  const refusal = await requireTenantMember(scope?.tenantId);
  if (refusal) throw new Error(refusal);
  if (String(scope?.projectId) !== String(versionRow.project_id)) throw new Error(NOT_FOUND);
  return helper.buildOpenApiSpecJsonForVersion(...args);
}

// ---- Canvas layouts -----------------------------------------------------------------------------

/**
 * Allow a layout read when the version is in one of the caller's workspaces and any user id named
 * is the caller's own.
 */
function layoutCheck(versionId: unknown, userId: unknown, tenantId?: unknown): Promise<Refusal> {
  return requireSelfOrNobody(userId).then(async (refusal) => {
    if (refusal) return refusal;
    const tenant = await tenantOfVersion(versionId);
    if (tenantId !== undefined && tenantId !== null && tenantId !== tenant) return NOT_FOUND;
    return requireTenantMember(tenant);
  });
}

export async function getDefaultCanvasLayout(...args: Parameters<typeof helper.getDefaultCanvasLayout>) {
  return guarded(layoutCheck(args[0], args[1]), () => helper.getDefaultCanvasLayout(...args));
}

export async function getEffectiveDefaultLayoutName(
  ...args: Parameters<typeof helper.getEffectiveDefaultLayoutName>
) {
  return guarded(layoutCheck(args[0], args[1], args[2]), () => helper.getEffectiveDefaultLayoutName(...args));
}

export async function getNamedCanvasLayout(...args: Parameters<typeof helper.getNamedCanvasLayout>) {
  return guarded(layoutCheck(args[0], args[1]), () => helper.getNamedCanvasLayout(...args));
}

// ---- API keys -----------------------------------------------------------------------------------

export async function getApiKeysForTenant(...args: Parameters<typeof helper.getApiKeysForTenant>) {
  return guarded(requireTenantPermission(args[0], 'api_keys:view'), () => helper.getApiKeysForTenant(...args));
}

/** A new key acts with the workspace's authority over REST, so it needs `api_keys:create` there. */
export async function createApiKey(...args: Parameters<typeof helper.createApiKey>) {
  return guarded(requireTenantPermission(args[0], 'api_keys:create'), () => helper.createApiKey(...args));
}

export async function deleteApiKey(...args: Parameters<typeof helper.deleteApiKey>) {
  return guarded(
    tenantOfApiKey(args[0]).then((tenant) => requireTenantPermission(tenant, 'api_keys:delete')),
    () => helper.deleteApiKey(...args)
  );
}

export async function toggleApiKeyStatus(...args: Parameters<typeof helper.toggleApiKeyStatus>) {
  return guarded(
    tenantOfApiKey(args[0]).then((tenant) => requireTenantPermission(tenant, 'api_keys:edit')),
    () => helper.toggleApiKeyStatus(...args)
  );
}
