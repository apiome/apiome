import { NextResponse } from 'next/server';
import { forwardExportDelivery, jsonBodyOr400 } from '@lib/export-delivery-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ preset: string }> };

/**
 * GET / PATCH / DELETE /api/export/presets/{preset} — one export preset, by id or name (MFX-39.3).
 *
 * `PATCH` changes its name, description, targets (replaced whole) or delivery profile (`null` removes it).
 */
export async function GET(_request: Request, { params }: Params) {
  const { preset } = await params;
  return forwardExportDelivery('GET', `/presets/${encodeURIComponent(preset)}`);
}

export async function PATCH(request: Request, { params }: Params) {
  const { preset } = await params;
  const body = await jsonBodyOr400(request);
  if (body instanceof NextResponse) return body;
  return forwardExportDelivery('PATCH', `/presets/${encodeURIComponent(preset)}`, body);
}

export async function DELETE(_request: Request, { params }: Params) {
  const { preset } = await params;
  return forwardExportDelivery('DELETE', `/presets/${encodeURIComponent(preset)}`);
}
