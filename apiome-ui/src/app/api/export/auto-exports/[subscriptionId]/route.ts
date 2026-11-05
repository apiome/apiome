import { NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ subscriptionId: string }> };

/**
 * PATCH / DELETE /api/export/auto-exports/{subscriptionId} — change (`haltAt`, `approveLoss`, `active`) or
 * remove an auto-export subscription (MFX-39.4, #4336).
 */
export async function PATCH(request: Request, { params }: Params) {
  const { subscriptionId } = await params;
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('PATCH', `/auto-exports/${encodeURIComponent(subscriptionId)}`, body);
}

export async function DELETE(_request: Request, { params }: Params) {
  const { subscriptionId } = await params;
  return forwardExportDelivery('DELETE', `/auto-exports/${encodeURIComponent(subscriptionId)}`);
}
