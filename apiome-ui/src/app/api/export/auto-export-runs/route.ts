import { NextRequest } from 'next/server';
import { forwardExportDelivery } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/auto-export-runs — what each publish's auto-exports did, newest first (MFX-39.4, #4336).
 * `?projectId=` / `?subscriptionId=` / `?limit=` narrow.
 */
export async function GET(request: NextRequest) {
  const params = new URLSearchParams();
  for (const key of ['projectId', 'subscriptionId', 'limit'] as const) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return forwardExportDelivery('GET', `/auto-export-runs${query ? `?${query}` : ''}`);
}
