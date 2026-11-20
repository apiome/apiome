/**
 * A project version's external `$ref`s, cycles and policy — COA-2.8 (#7051).
 *
 * `GET /api/projects/[projectId]/references?version=…` forwards to apiome-rest
 * `/v1/projects/{tenant}/{project}/references`.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardReferences, referencesPath } from '@lib/project-references-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ projectId: string }> };

/**
 * List the references.
 *
 * @returns `{success, data}` or `{success: false, error, code}`.
 */
export async function GET(request: NextRequest, context: Context): Promise<NextResponse> {
  const { projectId } = await context.params;
  const version = new URL(request.url).searchParams.get('version');
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return forwardReferences('GET', (tenant) => `${referencesPath(tenant, projectId)}${query}`);
}
