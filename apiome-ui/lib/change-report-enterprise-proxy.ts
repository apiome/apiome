/**
 * Shared helpers for the enterprise change-report proxy routes (#2705): the review transitions
 * (`submit`, `approve`, `reject`), the PDF export and the audit list.
 *
 * Each route resolves the signed-in tenant, forwards to apiome-rest with the user's JWT, and
 * answers `{ success, … }` like the other change-report proxies. The REST layer enforces who
 * may do what and the `change-report-enterprise` entitlement; nothing is decided here.
 */

import { NextRequest, NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import {
  getAuthenticatedTenantContext,
  proxyRestPost,
  type SessionUser,
} from '@lib/primitives-api-proxy';

/** The three review transitions a change report can make. */
export type ChangeReportTransition = 'submit' | 'approve' | 'reject';

/** What a route needs to call apiome-rest for one version's change report. */
export type ChangeReportTarget =
  | { ok: true; user: SessionUser; restPath: string }
  | { ok: false; response: NextResponse };

/**
 * Resolve the signed-in tenant and the REST path of a version's change report.
 *
 * @param request The incoming request; its `projectId` query parameter is required.
 * @param versionId The version id from the route.
 * @returns The user and `/versions/{tenant}/{project}/{version}/change-report`, or the error
 *   response to return as is.
 */
export async function resolveChangeReportTarget(
  request: NextRequest,
  versionId: string
): Promise<ChangeReportTarget> {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return {
      ok: false,
      response: NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status }),
    };
  }
  const projectId = new URL(request.url).searchParams.get('projectId');
  if (!projectId) {
    return {
      ok: false,
      response: NextResponse.json(
        { success: false, error: 'Project ID is required' },
        { status: 400 }
      ),
    };
  }
  const restPath = `/versions/${encodeURIComponent(ctx.tenantSlug)}/${encodeURIComponent(
    projectId
  )}/${encodeURIComponent(versionId)}/change-report`;
  return { ok: true, user: ctx.user, restPath };
}

/**
 * Proxy one review transition.
 *
 * @param request The incoming POST; an optional JSON body carries the reviewer's `note`.
 * @param versionId The version id from the route.
 * @param transition `submit`, `approve` or `reject`.
 * @returns `{ success: true, report }`, or `{ success: false, error }` with the REST status.
 */
export async function proxyChangeReportTransition(
  request: NextRequest,
  versionId: string,
  transition: ChangeReportTransition
): Promise<NextResponse> {
  try {
    const target = await resolveChangeReportTarget(request, versionId);
    if (!target.ok) return target.response;

    // `submit` takes no body; a missing or malformed one is simply "no note".
    const body =
      transition === 'submit' ? undefined : await request.json().catch(() => ({}));

    const { data, error, status } = await proxyRestPost(
      target.user,
      `${target.restPath}/${transition}`,
      body
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, report: data });
  } catch (error) {
    console.error(`change-report ${transition}:`, error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * Fetch a binary or JSON resource from apiome-rest as the signed-in user, without parsing it.
 *
 * @param user The signed-in user.
 * @param path The REST path (after the `/v1` base).
 * @returns The raw REST response.
 */
export function fetchRestRaw(user: SessionUser, path: string): Promise<Response> {
  return fetch(`${REST_API_BASE_URL}${path}`, {
    method: 'GET',
    headers: createRestAuthHeaders(user),
    cache: 'no-store',
  });
}
