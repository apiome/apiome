import { NextRequest } from 'next/server';
import { proxyChangeReportTransition } from '@lib/change-report-enterprise-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/versions/[versionId]/change-report/submit?projectId=…  (#2705)
 *
 * Submit a draft change report for review (`draft` → `pending_review`). The version's creator or a
 * tenant administrator; the REST layer answers 409 when the report is not a draft.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  const { versionId } = await params;
  return proxyChangeReportTransition(request, versionId, 'submit');
}
