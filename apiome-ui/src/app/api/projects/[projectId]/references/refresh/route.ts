/**
 * Refresh a project version's external `$ref`s — COA-2.8 (#7051).
 *
 * `POST /api/projects/[projectId]/references/refresh` with `{version?, urls?}` forwards to
 * apiome-rest `…/references/refresh` (needs `projects:edit`).
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardReferences, readReferencesBody, referencesPath } from '@lib/project-references-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ projectId: string }> };

/**
 * Refresh.
 *
 * @returns `{success, data}` (the references after the refresh) or `{success: false, error, code}`.
 */
export async function POST(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readReferencesBody(request);
  if (body instanceof NextResponse) return body;
  const { projectId } = await context.params;
  return forwardReferences('POST', (tenant) => referencesPath(tenant, projectId, '/refresh'), body);
}
