/**
 * Shared forwarding for the `/api/pact/*` proxies (PFX-5.1, #6945; PFX-5.2, #6946; PFX-5.3, #6947).
 *
 * Each proxy resolves the signed-in user's workspace, forwards one read to apiome-rest as that
 * user, and passes REST's answer through (a 403 stays a 403). Tenant scoping and the `pacts`
 * permission are REST's: the proxy never names a tenant of its own and never widens a request.
 */

import { NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { createRestAuthHeaders } from '@lib/rest-auth';
import {
  RollupError,
  collectPacticipantEnvironments,
  pacticipantProxyPath,
  pickListQuery,
  withQuery,
  type RestRead,
  type RestReader,
} from '@lib/pact-pacticipants';
import { findPreviousDistinct } from '@lib/pact-detail';
import { collectPactNetwork } from '@lib/pact-network';

/** What the browser is told when apiome-rest cannot be reached. */
export const PACT_UNAVAILABLE = 'The Pact Broker is unavailable (apiome-rest not reachable). Try again shortly.';

/** A JSON error the browser reads as `{ success: false, error }`. */
export function pactError(status: number, error: string): NextResponse {
  return NextResponse.json({ success: false, error }, { status });
}

/**
 * Forward one fixed read (no query parameters) as the signed-in user.
 *
 * @param path - The REST path below `/v1/tenants/{slug}`.
 * @returns REST's answer.
 */
export async function forwardPactRead(path: string): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'GET',
    user: resolved.user,
    unavailable: PACT_UNAVAILABLE,
  });
}

/**
 * Forward one page of a list: the filters named in `allowed` and `cursor`, with a fixed page size.
 * Anything else in the query string is refused with a 400 that names it.
 *
 * @param search - The browser's query string.
 * @param path - The REST list path below `/v1/tenants/{slug}`.
 * @param allowed - The filters this list accepts besides `cursor`.
 * @param limit - The page size.
 * @returns REST's answer, or the 400.
 */
export async function forwardPactList(
  search: URLSearchParams,
  path: string,
  allowed: readonly string[],
  limit: number,
): Promise<NextResponse> {
  const picked = pickListQuery(search, allowed);
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactRead(withQuery(path, picked.query, limit));
}

/**
 * The REST path below one pacticipant, or `null` for a malformed handle (the proxy then answers
 * 404 without calling REST).
 *
 * @param slug - The handle from the route.
 * @param suffix - E.g. `versions`; empty for the pacticipant itself.
 * @returns The path, or `null`.
 */
export function pacticipantPath(slug: string, suffix = ''): string | null {
  const base = pacticipantProxyPath(slug);
  if (base === null) return null;
  return suffix ? `${base}/${suffix}` : base;
}

/**
 * The environments roll-up for one pacticipant, read as the signed-in user.
 *
 * @param slug - The pacticipant's handle (already checked).
 * @returns `{ environments }`, or REST's refusal of the environment list.
 */
export async function forwardPacticipantEnvironments(slug: string): Promise<NextResponse> {
  return answerWithReader((read) => collectPacticipantEnvironments(read, slug));
}

/**
 * The previous different pact of a consumer version (PFX-5.2, #6946), found by walking back
 * through the integration's versions as the signed-in user.
 *
 * @param provider - The provider's handle (already checked).
 * @param consumer - The consumer's handle (already checked).
 * @param version - The consumer version; the latest pact when `null`.
 * @returns The outcome and the previous pact, or REST's refusal of a read it needed.
 */
export async function forwardPreviousPact(
  provider: string,
  consumer: string,
  version: string | null,
): Promise<NextResponse> {
  return answerWithReader((read) => findPreviousDistinct(read, provider, consumer, version));
}

/**
 * The network of pacticipants connected to one (PFX-5.3, #6947), collected by reading each one's
 * matrix as the signed-in user.
 *
 * @param slug - The pacticipant's handle (already checked).
 * @returns The network, or REST's refusal of the pacticipant's own matrix.
 */
export async function forwardPactNetwork(slug: string): Promise<NextResponse> {
  return answerWithReader((read) => collectPactNetwork(read, slug));
}

/**
 * Run a roll-up of several REST reads as the signed-in user and answer with its result.
 *
 * @param run - The roll-up, given a reader of paths below `/v1/tenants/{slug}`.
 * @returns The result as JSON; a {@link RollupError} keeps REST's status; an unreachable REST is a 503.
 */
async function answerWithReader<T>(run: (read: RestReader) => Promise<T>): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const headers = createRestAuthHeaders(resolved.user);
  const read = async (path: string): Promise<RestRead> => {
    const rest = await fetch(tenantUrl(resolved.slug, path), { method: 'GET', headers, cache: 'no-store' });
    const body = await rest.json().catch(() => ({}));
    return { ok: rest.ok, status: rest.status, body };
  };
  try {
    return NextResponse.json(await run(read));
  } catch (caught) {
    if (caught instanceof RollupError) return pactError(caught.status >= 400 ? caught.status : 502, caught.message);
    return pactError(503, PACT_UNAVAILABLE);
  }
}
