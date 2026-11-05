import { NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ profileId: string }> };

/**
 * GET / PATCH / DELETE /api/export/delivery-profiles/{profileId} (MFX-38.4, #4331).
 *
 * Proxies REST `…/delivery-profiles/{profile_id}`: read one profile, change its name, description or
 * destination (`PATCH`, a webhook keeps its secret unless one is sent), or delete it (its deliveries
 * keep their record).
 */
export async function GET(_request: Request, { params }: Params) {
  const { profileId } = await params;
  return forwardExportDelivery('GET', `/delivery-profiles/${encodeURIComponent(profileId)}`);
}

export async function PATCH(request: Request, { params }: Params) {
  const { profileId } = await params;
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('PATCH', `/delivery-profiles/${encodeURIComponent(profileId)}`, body);
}

export async function DELETE(_request: Request, { params }: Params) {
  const { profileId } = await params;
  return forwardExportDelivery('DELETE', `/delivery-profiles/${encodeURIComponent(profileId)}`);
}
