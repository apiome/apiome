/**
 * A provider's standing contract sources — PFX-8.7 (#7304).
 *
 * - `GET ?provider=<name>` forwards `GET /v1/tenants/{slug}/pacticipants/{p}/contract-sources`: whether
 *   each published version of its project, and every push to a repository file, publish its contract.
 * - `PUT { provider, onProjectPublish?, repository?, bindProject? }` changes only what is sent (the rest
 *   of the setting is read and kept); with `bindProject` a provider bound to no project is bound to it
 *   first, and one bound to another project is refused with the reason. Unknown fields are a 400.
 *
 * Everything runs as the signed-in user: tenancy, `pacts:view` / `pacts:edit` and `imports:view` are REST's.
 */

import { NextRequest } from 'next/server';
import { sourcesPath } from '@lib/pact-contract-sources';
import { pickSourcesRequest, saveSources } from '@lib/pact-contract-sources-proxy';
import { answerWithRestCall, forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const extra = [...params.keys()].filter((key) => key !== 'provider');
  if (extra.length) return pactError(400, `Unknown parameter: ${extra.join(', ')}.`);
  const path = sourcesPath(params.get('provider') ?? '');
  if (!path) return pactError(400, 'provider is required.');
  return forwardPactRead(path);
}

export async function PUT(request: NextRequest) {
  const picked = pickSourcesRequest(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return answerWithRestCall((call) => saveSources(call, picked.provider, picked.patch));
}
