/**
 * The provider's spec for the **Write interactions** editor — PFX-8.5 (#7302).
 *
 * `GET ?provider=<name>` reads, as the signed-in user, the provider's pacticipant, its linked
 * project's latest revision document and mock scenarios, and its registered provider states, and
 * answers `{ provider, revision, operations, states, problems }` (see `@lib/pact-provider-spec`).
 * The editor checks paths, fills responses and suggests states from it. It reads only.
 *
 * Any other query parameter, a repeated or missing `provider` is a 400 without calling REST. Each
 * read carries the caller's own token, so the workspace and the permissions (`pacts:view`,
 * `versions:view`) are REST's: a refused pacticipant read keeps REST's status, and a refused part
 * (a project the caller cannot see) is named in `problems`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { resolveConnectorTenant } from '@lib/connectors-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { fetchAllPages } from '@lib/rest-paged-list';
import { loadProviderSpec, pickSpecQuery, type FetchJson } from '@lib/pact-provider-spec';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const picked = pickSpecQuery(request.nextUrl.searchParams);
  if (!picked.ok) return pactError(400, picked.error);
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const slug = encodeURIComponent(resolved.slug);
  const headers = createRestAuthHeaders(resolved.user);
  const fetchJson: FetchJson = async (url) => {
    try {
      // Lists (the project's revisions) are paged; a single read comes back as it is.
      const response = await fetchAllPages(url, { method: 'GET', headers, cache: 'no-store' });
      const text = await response.text();
      let body: unknown = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = { error: 'The answer was not JSON.' };
      }
      return { status: response.status, body };
    } catch {
      return null;
    }
  };
  const answer = await loadProviderSpec(
    picked.provider,
    {
      tenant: (path) => `${REST_API_BASE_URL}/tenants/${slug}/${path}`,
      versions: (path) => `${REST_API_BASE_URL}/versions/${slug}/${path}`,
    },
    fetchJson,
  );
  if ('error' in answer) return pactError(answer.status, answer.error);
  return NextResponse.json(answer);
}
