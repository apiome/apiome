import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ jobId: string }> };

/**
 * GET /api/export/runs/{jobId} — one run of the export history with its stored reports, read-only
 * (MFX-46.1). Proxies REST `GET /v1/export/{tenant}/runs/{job_id}`.
 */
export async function GET(_request: Request, { params }: Params) {
  const { jobId } = await params;
  return forwardExportDelivery('GET', `/runs/${encodeURIComponent(jobId)}`);
}
