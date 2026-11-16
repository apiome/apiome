/**
 * One stored overlay of a revision's chain — GVM-4.3 (#5878).
 *
 * `PUT    /api/versions/[versionId]/overlays/[overlayId]?projectId=…` replaces it in place.
 * `DELETE /api/versions/[versionId]/overlays/[overlayId]?projectId=…` removes it.
 * A published revision refuses both with `code: overlay-version-published`.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardVersionOverlays, readOverlayBody } from '@lib/version-overlays-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ versionId: string; overlayId: string }> };

/**
 * Replace the overlay (it keeps its position and gets a new id).
 *
 * @returns `{success, data: overlay}` or `{success: false, error, code}`.
 */
export async function PUT(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readOverlayBody(request);
  if (body instanceof NextResponse) return body;
  const { versionId, overlayId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'PUT', `/${encodeURIComponent(overlayId)}`, body);
}

/**
 * Remove the overlay.
 *
 * @returns `{success, data: null}` or `{success: false, error, code}`.
 */
export async function DELETE(request: NextRequest, context: Context): Promise<NextResponse> {
  const { versionId, overlayId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'DELETE', `/${encodeURIComponent(overlayId)}`);
}
