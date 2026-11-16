/**
 * A revision's stored overlay chain — GVM-4.3 (#5878).
 *
 * `GET  /api/versions/[versionId]/overlays?projectId=…` lists the chain (and the publish render).
 * `POST /api/versions/[versionId]/overlays?projectId=…` with `{name, source, document, position?}`
 * adds an overlay. Forwards to apiome-rest `…/v1/versions/{t}/{p}/{v}/overlays`.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardVersionOverlays, readOverlayBody } from '@lib/version-overlays-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ versionId: string }> };

/**
 * List the chain.
 *
 * @returns `{success, data: {overlays, published, render, …}}` or `{success: false, error, code}`.
 */
export async function GET(request: NextRequest, context: Context): Promise<NextResponse> {
  const { versionId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'GET');
}

/**
 * Add an overlay to a draft revision's chain.
 *
 * @returns `{success, data: overlay}` (201) or `{success: false, error, code}`.
 */
export async function POST(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readOverlayBody(request);
  if (body instanceof NextResponse) return body;
  const { versionId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'POST', '', body);
}
