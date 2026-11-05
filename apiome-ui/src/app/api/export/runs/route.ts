import { NextRequest } from 'next/server';
import { forwardExportDelivery } from '@lib/export-delivery-proxy';
import { exportRunQuery } from '@lib/export-history-query';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/runs — the workspace's export history (MFX-46.1, #4379): who exported what, where,
 * with how much loss. Proxies REST `GET /v1/export/{tenant}/runs` with its allow-listed filters.
 */
export async function GET(request: NextRequest) {
  return forwardExportDelivery('GET', `/runs${exportRunQuery(request.nextUrl.searchParams)}`);
}
