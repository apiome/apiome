/**
 * Preview a revision's stored overlay chain — GVM-4.3 (#5878).
 *
 * `GET /api/versions/[versionId]/overlays/preview?projectId=…` forwards to apiome-rest
 * `…/overlays/preview`: the resolved document, both fingerprints and the provenance ledger —
 * exactly what an export with the same chain renders.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardVersionOverlays } from '@lib/version-overlays-proxy';

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
