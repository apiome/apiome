import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/** GET /api/export/runs/actors — the people in the export history, for its actor filter (MFX-46.1). */
export async function GET() {
  return forwardExportDelivery('GET', '/runs/actors');
}
