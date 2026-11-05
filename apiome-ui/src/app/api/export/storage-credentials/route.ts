import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/storage-credentials — the workspace's S3-compatible bucket credentials (MFX-38.3),
 * described without secrets: what an object-storage delivery profile picks from (MFX-38.4, #4331).
 */
export async function GET() {
  return forwardExportDelivery('GET', '/storage-credentials');
}
