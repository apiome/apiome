/**
 * Preview a revision's stored overlay chain — GVM-4.3 (#5878).
 *
 * `GET /api/versions/[versionId]/overlays/preview?projectId=…` forwards to apiome-rest
 * `…/overlays/preview`: the resolved document, both fingerprints and the provenance ledger —
 * exactly what an export with the same chain renders.
 *
 * `POST` (COA-2.7, #7050) renders the same chain with an unsaved draft overlay
 * (`{draft: {name, document}, replace_overlay_id?}`), so the overlay manager can preview an edit
 * before saving it. Nothing is written.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardVersionOverlays, readOverlayBody } from '@lib/version-overlays-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ versionId: string }> };

/**
 * Render the chain.
 *
 * @returns `{success, data: {document, report, source_fingerprint, resolved_fingerprint}}`.
 */
export async function GET(request: NextRequest, context: Context): Promise<NextResponse> {
  const { versionId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'GET', '/preview');
}

/**
 * Render the chain with a draft overlay.
 *
 * @returns `{success, data: preview}` or `{success: false, error, code}`.
 */
export async function POST(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readOverlayBody(request);
  if (body instanceof NextResponse) return body;
  const { versionId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'POST', '/preview', body);
}
