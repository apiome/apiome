/**
 * Shared plumbing for the branch-to-draft binding BFF routes — GNC-2.1 (#4737).
 *
 * Every route under `/api/projects/[projectId]/bindings` does the same three things before
 * anything of its own: decide the tenant from the session (never from the browser), sign the
 * caller's apiome-rest token, and address apiome-rest's
 * `…/projects/{project}/versions/{version}/binding`.
 *
 * They add **no permission rules of their own**: apiome-rest enforces `projects:view` on the read
 * and `versions:edit` on every write, and — the part no BFF could do — proves the caller's stored
 * credential can actually read the repository before it writes anything. What this layer adds is
 * keeping the tenant slug and the signing secret out of the browser, and forwarding only the
 * fields `@lib/draft-bindings` whitelists, so a hand-made request cannot smuggle one through.
 */

import { NextResponse } from 'next/server';

import { getAuthSession } from '@lib/auth/server-session';
import { getTenantById } from '@lib/db/helper';
import { createRestAuthHeaders, REST_API_BASE_URL, type SessionUserForRest } from '@lib/rest-auth';

/** Who is asking, resolved from the session. */
export interface BindingsAuth {
  /** The session user, as the REST token carries it. */
  user: SessionUserForRest;
  /** The caller's current tenant id. */
  tenantId: string;
  /** That tenant's slug, which apiome-rest's binding routes are addressed by. */
  tenantSlug: string;
}

/** A failed apiome-rest call, carrying the status and the stable code to answer with. */
export class RestBindingsError extends Error {
  /** The HTTP status apiome-rest answered with (502 for an unreadable reply). */
  readonly status: number;

  /** apiome-rest's stable `binding-*` code, when it sent one. */
  readonly code: string | null;

  /**
   * @param message - What went wrong, fit to show.
   * @param status - The HTTP status to pass on.
   * @param code - The stable refusal code, when there is one.
   */
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'RestBindingsError';
    this.status = status;
    this.code = code;
  }
}

/**
 * Resolve the caller, or the response that ends the request.
 *
 * @returns The caller's user and tenant, or a 401 (no session), 400 (no tenant selected) or 404
 *   (tenant not found) response.
 */
export async function resolveBindingsAuth(): Promise<BindingsAuth | NextResponse> {
  const session = await getAuthSession();
  if (!session?.user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  const user = session.user as SessionUserForRest;
  const tenantId = user.current_tenant_id;
  if (!tenantId) {
    return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
  }
  const tenant = await getTenantById(tenantId);
  if (!tenant?.slug) {
    return NextResponse.json({ success: false, error: 'Tenant not found' }, { status: 404 });
  }
  return {
    user: {
      user_id: user.user_id,
      email: session.user.email,
      name: session.user.name,
      current_tenant_id: tenantId,
    },
    tenantId,
    tenantSlug: tenant.slug,
  };
}

/**
 * The version a request is about, taken from the query string.
 *
 * @param url - The request URL.
 * @returns The revision id or version label, or null when none was given.
 */
export function versionRefFromQuery(url: string): string | null {
  const value = new URL(url).searchParams.get('version');
  return value && value.trim() ? value.trim() : null;
}

/**
 * The apiome-rest URL of one of a project's endpoints.
 *
 * @param tenantSlug - The tenant slug.
 * @param projectRef - The project id or slug from the URL.
 * @param suffix - The path under the project, e.g. `/sync-plans/123`.
 * @returns The absolute URL.
 */
export function restProjectUrl(tenantSlug: string, projectRef: string, suffix = ''): string {
  return (
    `${REST_API_BASE_URL}/tenants/${encodeURIComponent(tenantSlug)}` +
    `/projects/${encodeURIComponent(projectRef)}${suffix}`
  );
}

/**
 * The apiome-rest URL of one version's binding endpoints.
 *
 * @param tenantSlug - The tenant slug.
 * @param projectRef - The project id or slug from the URL.
 * @param versionRef - The revision id or version label.
 * @param suffix - A sub-resource, e.g. `/check` or `/sync`.
 * @returns The absolute URL.
 */
export function restBindingUrl(
  tenantSlug: string,
  projectRef: string,
  versionRef: string,
  suffix = ''
): string {
  return restProjectUrl(
    tenantSlug,
    projectRef,
    `/versions/${encodeURIComponent(versionRef)}/binding${suffix}`
  );
}

/**
 * The message and stable code inside a failed apiome-rest reply.
 *
 * apiome-rest's binding errors carry `detail: {code, message}`; FastAPI's validation errors carry
 * `detail: [...]`; everything else a string.
 *
 * @param payload - The parsed reply, or null.
 * @param fallback - What to say when the reply says nothing usable.
 * @returns `{message, code}`.
 */
export function restErrorDetail(
  payload: unknown,
  fallback: string
): { message: string; code: string | null } {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return { message: detail, code: null };
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const record = detail as { message?: unknown; code?: unknown };
    return {
      message: typeof record.message === 'string' && record.message ? record.message : fallback,
      code: typeof record.code === 'string' && record.code ? record.code : null,
    };
  }
  if (Array.isArray(detail)) return { message: 'The request was not valid', code: null };
  const error = (payload as { error?: unknown } | null)?.error;
  return { message: typeof error === 'string' && error ? error : fallback, code: null };
}

/**
 * Call one of the binding endpoints and parse its reply.
 *
 * `cache: 'no-store'` on every call: whether a bound branch has moved is exactly the kind of
 * answer that must not come from a cache the reader has already acted on.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @param versionRef - The revision id or version label.
 * @param init - `method`, `suffix` and the sanitized `body`.
 * @returns The parsed reply.
 * @throws RestBindingsError when apiome-rest refuses or answers with something unreadable.
 */
export async function callRestBinding(
  auth: BindingsAuth,
  projectRef: string,
  versionRef: string,
  init: { method?: 'GET' | 'POST' | 'DELETE'; suffix?: string; body?: unknown } = {}
): Promise<unknown> {
  return callRestUrl(
    auth,
    restBindingUrl(auth.tenantSlug, projectRef, versionRef, init.suffix ?? ''),
    init
  );
}

/**
 * Call one of the project-level endpoints these routes forward to, and parse its reply.
 *
 * The merge results of GNC-2.3 are addressed under the project rather than under a version — a
 * plan id is unique on its own — so they need this rather than {@link callRestBinding}. Everything
 * else about the call is identical, which is why both share {@link callRestUrl}.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @param init - `method`, the path `suffix` under the project, and the sanitized `body`.
 * @returns The parsed reply.
 * @throws RestBindingsError when apiome-rest refuses or answers with something unreadable.
 */
export async function callRestProject(
  auth: BindingsAuth,
  projectRef: string,
  init: { method?: 'GET' | 'POST' | 'DELETE'; suffix?: string; body?: unknown } = {}
): Promise<unknown> {
  return callRestUrl(auth, restProjectUrl(auth.tenantSlug, projectRef, init.suffix ?? ''), init);
}

/**
 * Issue one signed call to apiome-rest and parse its reply.
 *
 * @param auth - The caller.
 * @param url - The absolute apiome-rest URL.
 * @param init - `method` and the sanitized `body`.
 * @returns The parsed reply.
 * @throws RestBindingsError when apiome-rest refuses or answers with something unreadable.
 */
async function callRestUrl(
  auth: BindingsAuth,
  url: string,
  init: { method?: 'GET' | 'POST' | 'DELETE'; body?: unknown }
): Promise<unknown> {
  const response = await fetch(url, {
    method: init.method ?? 'GET',
    headers: createRestAuthHeaders(auth.user),
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    cache: 'no-store',
  });

  const raw = await response.text();
  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const { message, code } = restErrorDetail(payload, raw || 'The binding request failed');
    throw new RestBindingsError(message, response.status || 502, code);
  }
  if (!payload || typeof payload !== 'object') {
    throw new RestBindingsError('Unexpected reply from the binding API', 502);
  }
  return payload;
}

/**
 * The response for a failure while serving a binding route.
 *
 * @param error - What was thrown.
 * @param label - Where it happened, for the server log.
 * @returns `{success: false, error, code?}` with apiome-rest's status, or 500.
 */
export function bindingsErrorResponse(error: unknown, label: string): NextResponse {
  if (error instanceof RestBindingsError) {
    return NextResponse.json(
      { success: false, error: error.message, ...(error.code ? { code: error.code } : {}) },
      { status: error.status }
    );
  }
  console.error(`${label}:`, error);
  const message = error instanceof Error && error.message ? error.message : 'Internal server error';
  return NextResponse.json({ success: false, error: message }, { status: 500 });
}

/** The 400 answered when a request names no version. */
export function missingVersionResponse(): NextResponse {
  return NextResponse.json(
    { success: false, error: 'A version is required' },
    { status: 400 }
  );
}
