import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/export/auto-export-runs/{runId}/release — deliver a halted auto-export anyway (MFX-39.4, #4336).
 */
export async function POST(_request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return forwardExportDelivery('POST', `/auto-export-runs/${encodeURIComponent(runId)}/release`, {});
}
