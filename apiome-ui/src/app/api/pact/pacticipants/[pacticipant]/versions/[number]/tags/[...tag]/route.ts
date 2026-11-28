/**
 * Tag a version — PFX-8.11 (#7308).
 *
 * Proxies `PUT /v1/tenants/{slug}/pacticipants/{pacticipant}/versions/{number}/tags/{tag}`: the
 * Versions tab's inline **+ tag** and the bulk **Add a tag**. Tagging a version that already has
 * the tag changes nothing. A tag may contain `/` (`feat/new-invoice`), so it is the rest of the
 * path. A malformed handle is a 404; a number or tag REST would refuse (empty, padded, over 255
 * characters, control characters) a 400; both without calling apiome-rest. Permissions
 * (`pacts:create`), tenant scoping and an unknown version (404) are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardPactWrite, pacticipantPath, pactError } from '@lib/pact-proxy';
import {
  tagPathSegment,
  tagProblem,
  versionNumberProblem,
  versionProxyPath,
} from '@lib/pact-pacticipant-versions';

export const dynamic = 'force-dynamic';

export async function PUT(
  _request: NextRequest,
  context: { params: Promise<{ pacticipant: string; number: string; tag: string[] }> },
) {
  const { pacticipant, number, tag: parts } = await context.params;
  const problem = versionNumberProblem(number);
  if (problem) return pactError(400, problem);
  const tag = (parts ?? []).join('/');
  const refused = tagProblem(tag);
  if (refused) return pactError(400, refused);
  const path = versionProxyPath(pacticipantPath(pacticipant), number, `tags/${tagPathSegment(tag)}`);
  if (path === null) return pactError(404, 'Unknown pacticipant.');
  return forwardPactWrite(path, 'PUT');
}
