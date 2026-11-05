import { NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ jobId: string }> };

/**
 * GET /api/export/jobs/{jobId}/deliveries — every delivery of one export job across git, webhook
 * and object storage (MFX-38.4, #4331).
 *
 * POST /api/export/jobs/{jobId}/deliveries — deliver the completed job now with a profile:
 * `{ profileId }`. A delivery that reaches its destination and fails still answers `200` with
 * `outcome: failed`.
 */
export async function GET(_request: Request, { params }: Params) {
  const { jobId } = await params;
  return forwardExportDelivery('GET', `/jobs/${encodeURIComponent(jobId)}/deliveries`);
}

export async function POST(request: Request, { params }: Params) {
  const { jobId } = await params;
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('POST', `/jobs/${encodeURIComponent(jobId)}/deliveries`, {
    profileId: body.profileId,
  });
}
