/**
 * Pin or unpin an external `$ref` — COA-2.8 (#7051).
 *
 * `PUT /api/projects/[projectId]/references/pin` with `{url}` pins the last fetched snapshot;
 * `DELETE …/pin?url=…` removes the pin. Both forward to apiome-rest (needs `projects:edit`).
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardReferences, readReferencesBody, referencesPath } from '@lib/project-references-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ projectId: string }> };

/**
 * Pin.
 *
 * @returns `{success, data: reference}` or `{success: false, error, code}` (`ref-not-fetched`).
 */
export async function PUT(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readReferencesBody(request);
  if (body instanceof NextResponse) return body;
  const { projectId } = await context.params;
  return forwardReferences('PUT', (tenant) => referencesPath(tenant, projectId, '/pin'), body);
}

/**
 * Unpin.
 *
 * @returns `{success, data: reference}` or `{success: false, error, code}` (`ref-not-found`).
 */
export async function DELETE(request: NextRequest, context: Context): Promise<NextResponse> {
  const { projectId } = await context.params;
  const url = new URL(request.url).searchParams.get('url');
  if (!url) {
    return NextResponse.json({ success: false, error: 'url is required' }, { status: 400 });
  }
  return forwardReferences(
    'DELETE',
    (tenant) => `${referencesPath(tenant, projectId, '/pin')}?url=${encodeURIComponent(url)}`
  );
}
