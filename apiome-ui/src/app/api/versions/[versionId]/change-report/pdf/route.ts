import { NextRequest, NextResponse } from 'next/server';
import { fetchRestRaw, resolveChangeReportTarget } from '@lib/change-report-enterprise-proxy';
import { restErrorMessage } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/versions/[versionId]/change-report/pdf?projectId=…  (#2705)
 *
 * Download an approved change report as a PDF. The file is passed through unchanged, with the
 * REST layer's `Content-Disposition` and `X-Content-SHA256` (the hash stored with the report).
 * A report that is not approved answers 409 as `{ success: false, error }`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ versionId: string }> }
) {
  try {
    const { versionId } = await params;
    const target = await resolveChangeReportTarget(request, versionId);
    if (!target.ok) return target.response;

    const response = await fetchRestRaw(target.user, `${target.restPath}/pdf`);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      return NextResponse.json(
        {
          success: false,
          error: restErrorMessage(payload) || 'The change report could not be exported',
        },
        { status: response.status }
      );
    }

    const headers = new Headers({ 'Content-Type': 'application/pdf', 'Cache-Control': 'no-store' });
    for (const name of ['content-disposition', 'x-content-sha256']) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new NextResponse(await response.arrayBuffer(), { status: 200, headers });
  } catch (error) {
    console.error('change-report pdf:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
