import { NextRequest, NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/export/auto-exports — auto-export subscriptions: presets run on every publish of a project
 * (MFX-39.4, #4336). `?projectId=` / `?preset=` narrow.
 *
 * POST /api/export/auto-exports — subscribe: `{ projectId, preset, haltAt?, approveLoss?, active? }`.
 */
export async function GET(request: NextRequest) {
  const params = new URLSearchParams();
  for (const key of ['projectId', 'preset'] as const) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return forwardExportDelivery('GET', `/auto-exports${query ? `?${query}` : ''}`);
}

export async function POST(request: NextRequest) {
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('POST', '/auto-exports', body);
}
