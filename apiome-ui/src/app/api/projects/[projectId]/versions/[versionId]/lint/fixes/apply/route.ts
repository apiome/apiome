/**
 * POST /api/projects/[projectId]/versions/[versionId]/lint/fixes/apply — GVM-3.6 (#5874).
 *
 * Proxies to REST `POST /v1/versions/{tenantSlug}/{projectId}/{versionId}/lint/fixes/apply`
 * (GVM-3.2). Only `fixIds` and `reason` are forwarded: the UI applies named, ready fixes and
 * never renames. The server creates a new `lint-fix` revision, re-lints it and stores its
 * report; refusals (`409 lint-fix-version-published`, `422 lint-fix-breaking`, …) come back with
 * their status and `detail: { code, message }`.
 */
import { NextRequest, NextResponse } from 'next/server';
import { proxyToRest, requireSessionUser } from '@/app/api/lint/workspace/proxy';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string; versionId: string }> },
) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
  const raw = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
  const fixIds = Array.isArray(raw.fixIds)
    ? raw.fixIds.filter((id): id is string => typeof id === 'string' && id.length > 0)
    : [];
  const reason = typeof raw.reason === 'string' ? raw.reason.trim() : '';
  if (fixIds.length === 0 || !reason) {
    return NextResponse.json(
      { success: false, error: 'Name the fixes to apply (fixIds) and give a reason.' },
      { status: 400 },
    );
  }
  const { projectId, versionId } = await params;
  const path =
    `/versions/${encodeURIComponent(auth.tenantSlug)}/${encodeURIComponent(projectId)}` +
    `/${encodeURIComponent(versionId)}/lint/fixes/apply`;
  return proxyToRest(auth, path, { method: 'POST', body: { fixIds, reason } });
}
