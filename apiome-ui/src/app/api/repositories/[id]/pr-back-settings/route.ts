/**
 * A repository's PR-back settings — REPO-5.8 (#2793).
 *
 * Proxies `GET/PUT /v1/tenants/{slug}/repositories/{id}/pr-back-settings`. apiome-rest enforces
 * `imports:view` / `imports:edit`, validates every field and audits the save; this layer keeps
 * the tenant and signing secret server-side and forwards only the whitelisted fields
 * ({@link sanitizePrBackSettingsInput}).
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizePrBackSettingsInput } from '@lib/pr-back';

import {
  bindingsErrorResponse,
  callRestUrl,
  resolveBindingsAuth,
  restRepositoryUrl,
} from '../../../projects/[projectId]/bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** The 400 for a malformed repository id. */
function invalidId(): NextResponse {
  return NextResponse.json({ success: false, error: 'Invalid repository id' }, { status: 400 });
}

/**
 * Read the repository's PR-back settings.
 *
 * @param _request - Unused.
 * @param context - Route params carrying the repository id.
 * @returns `{success: true, ...settings}` or `{success: false, error}`.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    if (!UUID_RE.test(id)) return invalidId();
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestUrl(auth, restRepositoryUrl(auth.tenantSlug, id, '/pr-back-settings'), {});
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'repository pr-back settings GET');
  }
}

/**
 * Save the repository's PR-back settings.
 *
 * @param request - Carries the settings.
 * @param context - Route params carrying the repository id.
 * @returns `{success: true, ...settings}` or `{success: false, error, code?}`.
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    if (!UUID_RE.test(id)) return invalidId();
    const body = sanitizePrBackSettingsInput(await request.json().catch(() => null));
    if (!body) {
      return NextResponse.json({ success: false, error: 'Invalid settings' }, { status: 400 });
    }
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestUrl(auth, restRepositoryUrl(auth.tenantSlug, id, '/pr-back-settings'), {
      method: 'PUT',
      body,
    });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'repository pr-back settings PUT');
  }
}
