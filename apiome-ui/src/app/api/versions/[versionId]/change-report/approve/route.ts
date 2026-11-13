import { NextRequest } from 'next/server';
import { proxyChangeReportTransition } from '@lib/change-report-enterprise-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/versions/[versionId]/change-report/approve?projectId=…  (#2705)
 *
 * Approve a change report that is pending review, with an optional `note`. A tenant administrator
 * other than the submitter; an approved report can be exported as PDF.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  const { versionId } = await params;
  return proxyChangeReportTransition(request, versionId, 'approve');
}
