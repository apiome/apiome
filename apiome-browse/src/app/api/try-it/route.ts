/**
 * `POST /api/try-it` — the Try It CORS-safe relay route handler — SIM-3.2 (#4448).
 *
 * The browser cannot call arbitrary API hosts (CORS), so `sendViaProxy` (`lib/tryit/send.ts`)
 * posts composed Try It requests here and this handler relays them with undici. All policy and
 * pipeline logic lives in `lib/tryit/relay.ts` (framework-free, unit-tested); this module only
 * wires in the real network dependencies:
 *
 * - **DNS pre-check** via `node:dns` `lookup` with `all: true` — every resolved address is
 *   judged by the relay's IP guard before any connection is made.
 * - **Connect-time re-check** — the undici `Agent` used for guarded hops re-resolves inside the
 *   socket connect with the same guard, so a DNS-rebinding flip between the pre-check and the
 *   connect is also refused. The operator-configured mock origin uses a separate, unguarded
 *   agent (it is deployment infrastructure and often loopback in dev), and only when the hop
 *   matches that exact origin.
 * - **Allow-policy inputs** — the version's mock origin (env `APIOME_MOCK_PUBLIC_BASE_URL` +
 *   `mock_enabled`, mirroring the version page) and its declared spec `servers[]`
 *   (`getPublicVersionServers`) are looked up server-side from the request's context slugs, so
 *   the browser cannot forge the policy.
 *
 * Credential hygiene: nothing here logs URLs, headers, or bodies (query strings and headers can
 * carry credentials) — unexpected failures log the error message only. Request contents are
 * never persisted.
 */

import { lookup } from 'node:dns';
import type { LookupAddress, LookupOptions } from 'node:dns';
import { Agent, request as undiciRequest } from 'undici';
import type { Dispatcher } from 'undici';
import { getPublicVersionDetails, getPublicVersionServers } from '../../../../lib/db/helper';
import { buildMockBaseUrl } from '../../../../lib/mock/mockUrl';
import {
  deriveAllowedSpecOrigins,
  executeRelay,
  isBlockedIp,
  parseRelayEnvelope,
  SSRF_BLOCKED_CODE,
  type RelayHttpRequest,
  type RelayPolicy,
} from '../../../../lib/tryit/relay';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Shape of the callback `net.connect`/`tls.connect` pass to a custom `lookup`. */
type LookupCallback = (
  err: NodeJS.ErrnoException | null,
  address: string | LookupAddress[],
  family?: number
) => void;

/**
 * A `dns.lookup`-compatible resolver that fails the connection when any resolved address is
 * blocked by the SSRF guard. Wired into the guarded agent's socket connect, it re-validates
 * resolution at connect time — the defense against DNS rebinding between check and connect.
 */
function guardedLookup(hostname: string, options: LookupOptions, callback: LookupCallback): void {
  lookup(hostname, { ...options, all: true }, (err, addresses) => {
    if (err) {
      callback(err, options.all ? [] : '');
      return;
    }
    const list = addresses as LookupAddress[];
    if (list.length === 0 || list.some((entry) => isBlockedIp(entry.address))) {
      const blocked: NodeJS.ErrnoException = new Error(
        'The target resolved to a blocked address (SSRF guard).'
      );
      blocked.code = SSRF_BLOCKED_CODE;
      callback(blocked, options.all ? [] : '');
      return;
    }
    if (options.all) {
      callback(null, list);
    } else {
      callback(null, list[0].address, list[0].family);
    }
  });
}

/** Dispatcher for untrusted hops: every socket connect re-resolves through the SSRF guard. */
const guardedAgent = new Agent({ connect: { lookup: guardedLookup } });

/** Dispatcher for the operator-configured mock origin only (exempt from the IP guard). */
const mockOriginAgent = new Agent();

/** One HTTP exchange via undici, without following redirects (the relay follows manually). */
const relayHttpRequest: RelayHttpRequest = async (url, init) => {
  const response = await undiciRequest(url, {
    method: init.method as Dispatcher.HttpMethod,
    headers: init.headers,
    body: init.body ?? undefined,
    signal: init.signal,
    dispatcher: init.ipGuard ? guardedAgent : mockOriginAgent,
  });
  return {
    statusCode: response.statusCode,
    headers: response.headers,
    body: response.body,
  };
};

/** Resolve a hostname to all of its addresses for the relay's pre-connect SSRF check. */
function resolveAllAddresses(hostname: string): Promise<string[]> {
  return new Promise((resolvePromise, rejectPromise) => {
    lookup(hostname, { all: true }, (err, addresses) => {
      if (err) rejectPromise(err);
      else resolvePromise(addresses.map((entry) => entry.address));
    });
  });
}

/** JSON problem response (`{ detail }`), matching what `sendViaProxy` reads on refusals. */
function problem(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

/** The version's mock origin, or null when the mock is disabled or the env value is unusable. */
function resolveMockOrigin(
  mockEnabled: boolean,
  tenantSlug: string,
  projectSlug: string,
  versionId: string
): string | null {
  if (!mockEnabled) return null;
  const mockPublicBaseUrl = process.env.APIOME_MOCK_PUBLIC_BASE_URL || 'http://localhost:8775';
  const mockBaseUrl = buildMockBaseUrl(mockPublicBaseUrl, tenantSlug, projectSlug, versionId);
  if (!mockBaseUrl) return null;
  try {
    return new URL(mockBaseUrl).origin;
  } catch {
    return null;
  }
}

/** Generous ceiling for the relay POST itself (envelope JSON around the 1MB body cap). */
const MAX_ENVELOPE_BYTES = 4 * 1024 * 1024;

/**
 * Relay one composed Try It request.
 *
 * Refusals (allow-policy, SSRF guard, unknown version) are HTTP 403 with `{ detail }`; invalid
 * envelopes are HTTP 400; every upstream outcome — including synthesized 502/504 gateway
 * failures — is HTTP 200 with the response envelope, per the contract in `send.ts`.
 */
export async function POST(request: Request): Promise<Response> {
  const contentLength = Number(request.headers.get('content-length') ?? '0');
  if (Number.isFinite(contentLength) && contentLength > MAX_ENVELOPE_BYTES) {
    return problem(413, 'The relay request is too large.');
  }

  let raw: unknown;
  try {
    raw = await request.json();
  } catch {
    return problem(400, 'The relay request body is not valid JSON.');
  }

  const parsed = parseRelayEnvelope(raw);
  if (!parsed.ok) {
    return problem(400, parsed.detail);
  }
  const relayRequest = parsed.request;
  const { tenantSlug, projectSlug, versionSlug } = relayRequest.context;

  // Server-side allow-policy inputs; the browser only names the version, never the policy.
  const [version, serverRows] = await Promise.all([
    getPublicVersionDetails(tenantSlug, projectSlug, versionSlug),
    getPublicVersionServers(tenantSlug, projectSlug, versionSlug),
  ]);
  if (!version) {
    return problem(403, 'Unknown or unpublished API version.');
  }

  const policy: RelayPolicy = {
    mockOrigin: resolveMockOrigin(
      version.mock_enabled === true,
      tenantSlug,
      projectSlug,
      version.version_id
    ),
    specOrigins: deriveAllowedSpecOrigins(serverRows),
  };

  try {
    const outcome = await executeRelay(relayRequest, policy, {
      httpRequest: relayHttpRequest,
      resolve: resolveAllAddresses,
    });
    if (outcome.kind === 'refused') {
      return problem(403, outcome.detail);
    }
    return Response.json(outcome.envelope);
  } catch (err) {
    // Never log request contents — the message alone cannot carry the caller's credentials.
    console.error('[try-it] relay error:', err instanceof Error ? err.message : String(err));
    return problem(500, 'The Try It relay hit an unexpected error.');
  }
}
