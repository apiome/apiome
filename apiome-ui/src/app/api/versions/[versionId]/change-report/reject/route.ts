import { NextRequest } from 'next/server';
import { proxyChangeReportTransition } from '@lib/change-report-enterprise-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/versions/[versionId]/change-report/reject?projectId=…  (#2705)
 *
 * Send a change report that is pending review back to draft, with an optional `note`. Tenant
 * administrators only.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  const { versionId } = await params;
  return proxyChangeReportTransition(request, versionId, 'reject');
}
