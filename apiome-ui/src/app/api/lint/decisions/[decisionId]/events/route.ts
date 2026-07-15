/**
 * GET /api/lint/decisions/{decisionId}/events — remediation history for one finding
 * decision (CLX-1.3 audit trail, surfaced by the CLX-4.1 workspace detail dialog, #4859).
 */
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/route';
import { createRestAuthHeaders, REST_API_BASE_URL, SessionUserForRest } from '@lib/rest-auth';

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ decisionId: string }> },
) {
  try {
    const session = await getServerSession(authOptions);
    if (!session?.user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const user = session.user as SessionUserForRest;
    if (!user.current_tenant_id) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }
    const { decisionId } = await params;
    const response = await fetch(
      `${REST_API_BASE_URL}/lint/decisions/${encodeURIComponent(decisionId)}/events`,
      { method: 'GET', headers: createRestAuthHeaders(user) },
    );
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const payload = typeof data === 'object' && data ? data : {};
      const error =
        (payload as { detail?: string }).detail ?? `HTTP ${response.status}`;
      return NextResponse.json({ success: false, error }, { status: response.status });
    }
    return NextResponse.json({ success: true, events: Array.isArray(data) ? data : [] });
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Internal server error';
    return NextResponse.json({ success: false, error: msg }, { status: 500 });
  }
}
