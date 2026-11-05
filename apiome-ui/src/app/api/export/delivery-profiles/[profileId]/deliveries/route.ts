import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/delivery-profiles/{profileId}/deliveries — every delivery made with one profile,
 * across export jobs, newest first (MFX-38.4, #4331). Proxies REST `…/delivery-profiles/{id}/deliveries`.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ profileId: string }> }) {
  const { profileId } = await params;
  return forwardExportDelivery('GET', `/delivery-profiles/${encodeURIComponent(profileId)}/deliveries`);
}
