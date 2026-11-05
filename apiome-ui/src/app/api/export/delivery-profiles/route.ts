import { NextRequest, NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/delivery-profiles — the workspace's export delivery profiles (MFX-38.4, #4331).
 *
 * Proxies REST `GET /v1/export/{tenant}/delivery-profiles`; `?channel=git|webhook|object_storage`
 * narrows. No profile ever carries a secret.
 *
 * POST /api/export/delivery-profiles — store one: `{ name, description?, channel, git? | webhook? |
 * objectStorage? }`, forwarded verbatim (a webhook `secret` is sealed by the REST layer on arrival).
 */
export async function GET(request: NextRequest) {
  const channel = request.nextUrl.searchParams.get('channel');
  const query = channel ? `?channel=${encodeURIComponent(channel)}` : '';
  return forwardExportDelivery('GET', `/delivery-profiles${query}`);
}

export async function POST(request: NextRequest) {
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('POST', '/delivery-profiles', body);
}
