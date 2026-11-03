/**
 * Per-branch repository refresh rules (RAR-6.4, #3541) — proxies to
 * `GET/PUT /v1/tenants/{slug}/repositories/{id}/branch-refresh-rules`.
 *
 * A rule names a branch exactly (`main`) or by glob (`release/*`) and sets, for the branches it
 * matches, whether they refresh, how often, and the version line a refresh lands in.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  forwardRepositorySettingsRequest,
  readRepositorySettingsBody,
} from '@lib/repository-settings-proxy';

export const dynamic = 'force-dynamic';

const SUBPATH = 'branch-refresh-rules';
const ENVELOPE = 'branchRefresh';

/**
 * Read the repository's branch rules and each tracked branch's effective settings.
 *
 * @param _request Unused; the read takes no body.
 * @param params Route params carrying the repository id.
 * @returns The flattened branch-refresh projection.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  return forwardRepositorySettingsRequest({ repositoryId: id, method: 'GET', subpath: SUBPATH, envelope: ENVELOPE });
}

/**
 * Replace the repository's branch rules.
 *
 * @param request Carries `{ rules: [...] }`, the complete set.
 * @param params Route params carrying the repository id.
 * @returns The projection after the update.
 */
export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const { id } = await params;
  const parsed = await readRepositorySettingsBody(request);
  if ('error' in parsed) return parsed.error;
  return forwardRepositorySettingsRequest({
    repositoryId: id,
    method: 'PUT',
    subpath: SUBPATH,
    envelope: ENVELOPE,
    body: parsed.body,
  });
}
