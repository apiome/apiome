/**
 * GET /api/projects/[projectId]/versions/[versionId]/lint/fixes — GVM-3.6 (#5874).
 *
 * Proxies to REST `GET /v1/versions/{tenantSlug}/{projectId}/{versionId}/lint/fixes` (the
 * GVM-3.2 plan, `format=json`, default options: every rule the style guide turns on, no
 * renames) and adds one BFF fact the plan does not carry: `published`, read from
 * `GET /v1/versions/{tenantSlug}/{projectId}/{versionId}`, so the UI can show a published
 * revision's fixes as read-only instead of offering an apply the server refuses.
 *
 * Refusals are passed through with their status and `detail: { code, message }`.
 */
import { NextRequest, NextResponse } from 'next/server';
import { createRestAuthHeaders, getRestApiBaseUrl } from '@lib/rest-auth';
import { requireSessionUser } from '@/app/api/lint/workspace/proxy';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string; versionId: string }> },
) {
  const auth = await requireSessionUser();
  if ('error' in auth) return auth.error;
  try {
    const { projectId, versionId } = await params;
    const base =
      `${getRestApiBaseUrl()}/versions/${encodeURIComponent(auth.tenantSlug)}` +
      `/${encodeURIComponent(projectId)}/${encodeURIComponent(versionId)}`;
    const headers = createRestAuthHeaders(auth.user);
    const [planResponse, versionResponse] = await Promise.all([
      fetch(`${base}/lint/fixes?format=json`, { method: 'GET', headers }),
      fetch(base, { method: 'GET', headers }),
    ]);
    const plan = await planResponse.json().catch(() => null);
    const payload = typeof plan === 'object' && plan ? (plan as Record<string, unknown>) : {};
    if (!planResponse.ok) {
      return NextResponse.json(
        { success: false, error: `HTTP ${planResponse.status}`, ...payload },
        { status: planResponse.status },
      );
    }
    // The published flag is context: if the version read fails the plan is still shown and the
    // server's 409 on apply remains the authority.
    const version = versionResponse.ok ? await versionResponse.json().catch(() => null) : null;
    const published = Boolean(version && (version as { published?: unknown }).published === true);
    return NextResponse.json({ success: true, ...payload, published });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
