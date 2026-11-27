/**
 * Shared forwarding for the `/api/pact/*` proxies (PFX-5.1, #6945; PFX-5.2, #6946; PFX-5.3, #6947;
 * PFX-5.4, #6948; PFX-5.5, #6949; PFX-5.6, #6950).
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
import { retryAfterSeconds } from '@lib/pact-matrix';
import { collectWebhooks } from '@lib/pact-webhooks';
import type { RestCall } from '@lib/pact-provider-contract-proxy';

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
 * Forward one matrix or can-i-deploy read as the signed-in user (PFX-5.4, #6948). Like
 * {@link forwardPactRead}, plus REST's `Retry-After` (sent while the verdict is unknown) as
 * `retryAfterSeconds` in the body, so the page can say when asking again is worthwhile.
 *
 * @param path - The REST path below `/v1/tenants/{slug}`, with its (already checked) query.
 * @returns REST's matrix document with `retryAfterSeconds`, or REST's refusal.
 */
export async function forwardPactVerdict(path: string): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  try {
    const rest = await fetch(tenantUrl(resolved.slug, path), {
      method: 'GET',
      headers: createRestAuthHeaders(resolved.user),
      cache: 'no-store',
    });
    const body = (await rest.json().catch(() => ({}))) as unknown;
    if (!rest.ok) {
      return pactError(rest.status >= 400 ? rest.status : 502, failureMessage(body, `HTTP ${rest.status}`));
    }
    const document = body && typeof body === 'object' && !Array.isArray(body) ? body : {};
    return NextResponse.json({ ...document, retryAfterSeconds: retryAfterSeconds(rest.headers.get('Retry-After')) });
  } catch {
    return pactError(503, PACT_UNAVAILABLE);
  }
}

/**
 * Forward one console run (a re-run or verify-all-stale, PFX-5.5 #6949) as the signed-in user:
 * a `POST` of an already checked body. REST's refusal keeps its status and its message (a 409 for
 * a pair already running, a 403 without `pacts:create`).
 *
 * @param path - The REST path below `/v1/tenants/{slug}`.
 * @param body - The checked run body.
 * @returns REST's answer, or its refusal as `{ success: false, error }`.
 */
export async function forwardPactRun(path: string, body: unknown): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'POST',
    user: resolved.user,
    body,
    unavailable: PACT_UNAVAILABLE,
  });
}

/**
 * Forward one webhook write (PFX-5.6, #6950) as the signed-in user: create, replace, delete, test
 * or redeliver, with an already checked body. REST's refusal keeps its status and message (a 422
 * names the field, a 409 says why a delivery cannot be sent again, a 429 asks to wait).
 *
 * @param path - The REST path below `/v1/tenants/{slug}`.
 * @param method - `POST`, `PUT` or `DELETE`.
 * @param body - The checked body, or `undefined` for none.
 * @returns REST's answer, or its refusal as `{ success: false, error }`.
 */
export async function forwardPactWrite(
  path: string,
  method: 'POST' | 'PUT' | 'DELETE',
  body?: unknown,
): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method,
    user: resolved.user,
    body,
    unavailable: PACT_UNAVAILABLE,
  });
}

/**
 * The Webhooks page's read (PFX-5.6, #6950): every webhook and the newest firing of each, read as
 * the signed-in user.
 *
 * @returns `{ webhooks, latest }`, or REST's refusal of either read.
 */
export async function forwardWebhooksOverview(): Promise<NextResponse> {
  return answerWithReader((read) => collectWebhooks(read));
}

/** REST's message from a refusal (`detail` string or `detail.message`), or the fallback. */
function failureMessage(body: unknown, fallback: string): string {
  const detail = body && typeof body === 'object' ? (body as Record<string, unknown>).detail : undefined;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === 'string' && message) return message;
  }
  return fallback;
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

/**
 * Run a Publish-a-provider-contract handler (PFX-8.6, #7303) with REST calls made as the
 * signed-in user in their workspace, and answer with what it returns.
 *
 * @param handler - Gets a {@link RestCall} below `/v1/tenants/{slug}/`; returns the status and body.
 * @returns The answer, or the session's refusal (401 / 403) before any call.
 */
export async function answerWithRestCall(
  handler: (call: RestCall) => Promise<{ status: number; body: Record<string, unknown> }>,
): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const call: RestCall = async (method, path, body) => {
    try {
      const rest = await fetch(tenantUrl(resolved.slug, path), {
        method,
        headers: { ...createRestAuthHeaders(resolved.user), 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
      });
      return { status: rest.status, body: (await rest.json().catch(() => ({}))) as unknown };
    } catch {
      return null;
    }
  };
  const answer = await handler(call);
  return NextResponse.json(answer.body, { status: answer.status });
}
