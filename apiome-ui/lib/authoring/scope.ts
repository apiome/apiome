/**
 * Authoring scope: the Tenant → Project → Version → Environment selection that
 * every Authoring surface operates on (UXE-1.2).
 *
 * Scope lives in the URL so a copied link restores the same authorized view.
 * Tenant is deliberately *not* a URL parameter: it is owned by the session
 * (`user.current_tenant_id`) and switching it is a session-level action, so
 * putting it in the query string would let a link imply cross-tenant access
 * the viewer may not hold. The tenant is instead carried on the resolved scope
 * so children can key caches by it and drop stale cross-tenant data.
 */

import {
  DEFAULT_AUTHORING_ENVIRONMENT_ID,
  isAuthoringEnvironmentId,
  type AuthoringEnvironmentId,
} from './environments';

/** Query parameter carrying the selected project. */
export const AUTHORING_PROJECT_PARAM = 'projectId';
/** Query parameter carrying the selected version revision. */
export const AUTHORING_VERSION_PARAM = 'versionId';
/** Query parameter carrying the selected delivery environment lane. */
export const AUTHORING_ENVIRONMENT_PARAM = 'env';

/** Every scope parameter, in canonical order. */
export const AUTHORING_SCOPE_PARAMS = [
  AUTHORING_PROJECT_PARAM,
  AUTHORING_VERSION_PARAM,
  AUTHORING_ENVIRONMENT_PARAM,
] as const;

/** The portion of scope that round-trips through the URL. */
export type AuthoringUrlScope = {
  projectId: string | null;
  versionId: string | null;
  environmentId: AuthoringEnvironmentId;
};

/** URL scope plus the session-owned tenant it was resolved under. */
export type AuthoringScope = AuthoringUrlScope & {
  tenantId: string | null;
};

/** An empty scope on the default lane. */
export const EMPTY_AUTHORING_URL_SCOPE: AuthoringUrlScope = {
  projectId: null,
  versionId: null,
  environmentId: DEFAULT_AUTHORING_ENVIRONMENT_ID,
};

/** Anything that can be read like `URLSearchParams`. */
type ReadableParams = { get(name: string): string | null };

/**
 * Trim a raw parameter to a usable id.
 *
 * @param raw - Value read from a URL.
 * @returns The trimmed value, or `null` when absent or blank.
 */
function readId(raw: string | null | undefined): string | null {
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Read scope out of a query string.
 *
 * Unknown environments fall back to the default lane, and a version without a
 * project is discarded: a version id is meaningless without the project that
 * owns it, and honoring it would let a truncated link render another project's
 * data under the wrong heading.
 *
 * @param params - Search params, e.g. from `useSearchParams()`.
 * @returns The scope encoded in `params`.
 */
export function parseAuthoringScope(params: ReadableParams): AuthoringUrlScope {
  const projectId = readId(params.get(AUTHORING_PROJECT_PARAM));
  const rawVersionId = readId(params.get(AUTHORING_VERSION_PARAM));
  const rawEnvironment = readId(params.get(AUTHORING_ENVIRONMENT_PARAM));

  return {
    projectId,
    versionId: projectId ? rawVersionId : null,
    environmentId: isAuthoringEnvironmentId(rawEnvironment)
      ? rawEnvironment
      : DEFAULT_AUTHORING_ENVIRONMENT_ID,
  };
}

/**
 * Write scope into a copy of the given params, leaving unrelated parameters
 * (filters, selections) untouched so scope changes never discard a surface's
 * own query state.
 *
 * Empty values are removed rather than serialized as blanks, and the default
 * lane is omitted, so an unscoped URL stays clean.
 *
 * @param params - Existing search params to build on.
 * @param scope - Scope to encode.
 * @returns New params carrying `scope`.
 */
export function applyAuthoringScope(
  params: ReadableParams & Iterable<[string, string]>,
  scope: AuthoringUrlScope
): URLSearchParams {
  const next = new URLSearchParams(Array.from(params));

  if (scope.projectId) next.set(AUTHORING_PROJECT_PARAM, scope.projectId);
  else next.delete(AUTHORING_PROJECT_PARAM);

  if (scope.projectId && scope.versionId) next.set(AUTHORING_VERSION_PARAM, scope.versionId);
  else next.delete(AUTHORING_VERSION_PARAM);

  if (scope.environmentId && scope.environmentId !== DEFAULT_AUTHORING_ENVIRONMENT_ID) {
    next.set(AUTHORING_ENVIRONMENT_PARAM, scope.environmentId);
  } else {
    next.delete(AUTHORING_ENVIRONMENT_PARAM);
  }

  return next;
}

/**
 * Serialize scope on its own, for links built from scratch.
 *
 * @param scope - Scope to encode.
 * @returns A query string without the leading `?`, possibly empty.
 */
export function serializeAuthoringScope(scope: AuthoringUrlScope): string {
  return applyAuthoringScope(new URLSearchParams(), scope).toString();
}

/**
 * Build a scope-preserving href for an Authoring surface.
 *
 * @param path - Absolute route path, e.g. `/ade/authoring/scribe`.
 * @param scope - Scope to carry across the navigation.
 * @returns `path` with the scope query string appended when non-empty.
 */
export function buildAuthoringHref(path: string, scope: AuthoringUrlScope): string {
  const query = serializeAuthoringScope(scope);
  return query ? `${path}?${query}` : path;
}

/**
 * Compare two scopes by value.
 *
 * @param a - First scope.
 * @param b - Second scope.
 * @returns True when both select the same project, version and lane.
 */
export function authoringUrlScopesEqual(a: AuthoringUrlScope, b: AuthoringUrlScope): boolean {
  return (
    a.projectId === b.projectId &&
    a.versionId === b.versionId &&
    a.environmentId === b.environmentId
  );
}

/**
 * True when scope names a concrete project and version, i.e. child surfaces
 * have something to load rather than an empty state.
 *
 * @param scope - Scope to test.
 * @returns True when both project and version are selected.
 */
export function isAuthoringScopeResolved(scope: AuthoringUrlScope): boolean {
  return Boolean(scope.projectId && scope.versionId);
}
