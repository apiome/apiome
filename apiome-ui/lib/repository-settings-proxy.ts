/**
 * Shared forwarding for the repository settings proxy routes: the refresh conflict policy
 * (RAR-4.5, #3531), the per-branch refresh rules (RAR-6.4, #3541) and the workspace refresh
 * defaults (RAR-6.5, #3542).
 *
 * Each route talks to one `/v1/tenants/{slug}/repositories/{id}/<subpath>` REST surface with
 * the same auth, the same repository-id guard and the same error contract. REST nests its
 * projection under an envelope key (`conflictPolicy`, `branchRefresh`); the panels read one flat
 * object, so the envelope is flattened here and nowhere else.
 */

import { NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** One repository-settings request to forward. */
export interface RepositorySettingsRequest {
  /** The repository id from the route params; must be a UUID. */
  repositoryId: string;
  /** `GET` reads, `PUT` writes. */
  method: 'GET' | 'PUT';
  /** The REST sub-path under the repository (`conflict-policy`, `conflict-policy/file`, …). */
  subpath: string;
  /** The key REST nests its projection under (`conflictPolicy`, `branchRefresh`). */
  envelope: string;
  /** The payload of a write; omitted on a read. */
  body?: unknown;
}

/**
 * Forward one repository-settings request to REST and flatten its answer.
 *
 * REST's status is passed through rather than collapsed, because a panel has to tell its
 * failures apart: 400 means the request was refused (with REST's reason), 404 means the
 * repository is not this tenant's. A success is recognised by the envelope key, which the read
 * and every write return.
 *
 * @param request What to forward. See {@link RepositorySettingsRequest}.
 * @returns The response to hand back to the browser: `{ success: true, ...projection }`, or
 *   `{ success: false, error }` with REST's status (400 for a bad id, 503 when REST is down).
 */
export async function forwardRepositorySettingsRequest({
  repositoryId,
  method,
  subpath,
  envelope,
  body,
}: RepositorySettingsRequest): Promise<NextResponse> {
  if (!repositoryId || !UUID_RE.test(repositoryId)) {
    return NextResponse.json({ success: false, error: 'Invalid repository id' }, { status: 400 });
  }
  return forwardWorkspaceSettingsRequest({
    method,
    path: `repositories/${encodeURIComponent(repositoryId)}/${subpath}`,
    envelope,
    body,
  });
}

/** One workspace-level settings request to forward (no repository in the path). */
export interface WorkspaceSettingsRequest {
  /** `GET` reads, `PUT` writes. */
  method: 'GET' | 'PUT';
  /** The REST path under `/v1/tenants/{slug}/` (`repository-refresh-defaults`, …). */
  path: string;
  /** The key REST nests its projection under (`refreshDefaults`, …). */
  envelope: string;
  /** The payload of a write; omitted on a read. */
  body?: unknown;
}

/**
 * Forward one workspace-level settings request to REST and flatten its answer — the
 * workspace refresh defaults (RAR-6.5, #3542), and the repository routes above.
 *
 * @param request What to forward. See {@link WorkspaceSettingsRequest}.
 * @returns `{ success: true, ...projection }`, or `{ success: false, error }` with REST's status
 *   (403 for a non-administrator's write, 503 when REST is down).
 */
export async function forwardWorkspaceSettingsRequest({
  method,
  path,
  envelope,
  body,
}: WorkspaceSettingsRequest): Promise<NextResponse> {
  const context = await getAuthenticatedTenantContext();
  if (!context.ok) {
    return NextResponse.json({ success: false, error: context.error }, { status: context.status });
  }

  const url = `${REST_API_BASE_URL}/tenants/${encodeURIComponent(context.tenantSlug)}/${path}`;

  try {
    const rest = await fetch(url, {
      method,
      headers: {
        ...createRestAuthHeaders(context.user),
        ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      cache: 'no-store',
    });
    const text = await rest.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { raw: text };
    }
    if (rest.ok && parsed && typeof parsed === 'object' && envelope in parsed) {
      const projection = (parsed as Record<string, Record<string, unknown>>)[envelope];
      return NextResponse.json({ success: true, ...projection });
    }
    return NextResponse.json(
      { success: false, error: restErrorMessage(parsed) },
      { status: rest.status >= 400 ? rest.status : 502 }
    );
  } catch {
    return NextResponse.json(
      { success: false, error: 'Repository API unavailable (apiome-rest not reachable).' },
      { status: 503 }
    );
  }
}

/**
 * Read and parse a JSON request body.
 *
 * @param request The incoming request.
 * @returns The parsed body, or the 400 response for malformed JSON.
 */
export async function readRepositorySettingsBody(
  request: Request
): Promise<{ body: unknown } | { error: NextResponse }> {
  try {
    return { body: await request.json() };
  } catch {
    return {
      error: NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 }),
    };
  }
}
