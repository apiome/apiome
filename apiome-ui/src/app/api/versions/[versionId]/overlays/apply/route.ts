/**
 * Apply a revision's overlay chain as a new version — COA-2.7 (#7050).
 *
 * `POST /api/versions/[versionId]/overlays/apply?projectId=…` with `{version_label?}` forwards to
 * apiome-rest `…/overlays/apply`, which imports the resolved document as a new version of the same
 * project (through the import quality gate). REST enforces `versions:view`, `imports:create` and
 * `projects:edit` and refuses an empty chain (`overlay-chain-empty`), a chain that changes nothing
 * (`overlay-no-changes`) and a taken label (`version-exists`); the code is passed through.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardVersionOverlays, readOverlayBody } from '@lib/version-overlays-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ versionId: string }> };

/**
 * Apply the chain.
 *
 * @returns `{success, data: {version_record_id, version_label, …}}` or `{success: false, error, code}`.
 */
export async function POST(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readOverlayBody(request);
  if (body instanceof NextResponse) return body;
  const { versionId } = await context.params;
  return forwardVersionOverlays(request, versionId, 'POST', '/apply', body);
}
