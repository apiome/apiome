import { NextRequest, NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/presets — the workspace's export presets (MFX-39.3, #4335).
 *
 * POST /api/export/presets — store one: `{ name, description?, targets: [{target, options?}],
 * deliveryProfileId? }`, forwarded verbatim; the REST layer validates every target's options.
 */
export async function GET() {
  return forwardExportDelivery('GET', '/presets');
}

export async function POST(request: NextRequest) {
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('POST', '/presets', body);
}
