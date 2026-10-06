/**
 * Shared plumbing for the Agent access BFF routes — AGX-3.4 (#4540).
 *
 * Every route under `/api/agent-access` forwards to one of apiome-rest's agent-access surfaces,
 * all addressed under the caller's tenant:
 *
 * ```
 * /api/agent-access/toolsets/…   → /v1/tenants/{t}/agent-toolsets/…   (AGX-1.2)
 * /api/agent-access/keys/…       → /v1/tenants/{t}/agent-keys/…       (AGX-3.1 / 3.2)
 * /api/agent-access/usage        → /v1/tenants/{t}/agent-usage        (AGX-3.4 rollups)
 * ```
 *
 * The routes add **no permission rules of their own**: apiome-rest enforces `api_keys:view` on
 * every read and `api_keys:create` / `edit` / `delete` on the writes. What this layer adds is
 * deciding the tenant from the session (never from the browser), keeping the signing secret on
 * the server, and passing apiome-rest's refusal **code** through — the toolset editor needs
 * `agent-toolset-write-op-unconfirmed` to tell a missing confirmation from any other failure.
 *
 * The agent-key create reply carries the key's one-time secret. It is forwarded as-is and never
 * logged: this module logs only unexpected exceptions, never a reply body.
 */

import { NextResponse } from 'next/server';

import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

/** The HTTP verbs the agent-access routes forward. */
export type AgentAccessMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

/**
 * The message and stable code inside a failed apiome-rest reply.
 *
 * Agent-access refusals carry `detail: {code, errors: [...]}`; FastAPI validation errors carry
 * `detail: [{msg}, …]`; permission and auth failures carry a string.
 *
 * @param payload - The parsed reply, or null.
 * @param fallback - What to say when the reply says nothing usable.
 * @returns `{message, code}`; `code` is null when the reply had none.
 */
export function agentAccessErrorDetail(
  payload: unknown,
  fallback: string
): { message: string; code: string | null } {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail.trim()) return { message: detail, code: null };
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry as { msg?: unknown } | null)?.msg)
      .filter((msg): msg is string => typeof msg === 'string' && msg.trim().length > 0);
    return { message: messages.length ? messages.join('; ') : fallback, code: null };
  }
  if (detail && typeof detail === 'object') {
    const record = detail as { code?: unknown; errors?: unknown; message?: unknown };
    const errors = Array.isArray(record.errors)
      ? record.errors.filter((e): e is string => typeof e === 'string' && e.trim().length > 0)
      : [];
    const message =
      errors.length > 0
        ? errors.join('; ')
        : typeof record.message === 'string' && record.message.trim()
          ? record.message
          : fallback;
    return { message, code: typeof record.code === 'string' && record.code ? record.code : null };
  }
  return { message: fallback, code: null };
}

/**
 * Forward one request to apiome-rest's agent-access surface for the caller's tenant.
 *
 * @param method - The HTTP verb.
 * @param suffix - The path under `/v1/tenants/{t}`, starting with `/`, with every dynamic segment
 *   already `encodeURIComponent`-ed (e.g. `/agent-keys/<id>/allowlist`). May carry a query string.
 * @param body - The JSON body for a write, or undefined.
 * @returns `{success: true, data}` (with apiome-rest's status) or
 *   `{success: false, error, code?}` (with apiome-rest's status, or 401/400/404 for a missing
 *   session / tenant, or 500/502 for an unexpected failure).
 */
export async function forwardAgentAccess(
  method: AgentAccessMethod,
  suffix: string,
  body?: unknown
): Promise<NextResponse> {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  try {
    const response = await fetch(
      `${REST_API_BASE_URL}/tenants/${encodeURIComponent(ctx.tenantSlug)}${suffix}`,
      {
        method,
        headers: createRestAuthHeaders(ctx.user),
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
      }
    );

    if (response.status === 204) {
      return NextResponse.json({ success: true, data: null });
    }

    const raw = await response.text();
    let payload: unknown = null;
    try {
      payload = raw ? JSON.parse(raw) : null;
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const { message, code } = agentAccessErrorDetail(payload, raw || 'Request failed');
      return NextResponse.json(
        { success: false, error: message, ...(code ? { code } : {}) },
        { status: response.status >= 400 ? response.status : 502 }
      );
    }
    if (payload === null) {
      return NextResponse.json(
        { success: false, error: 'Unexpected reply from the agent access API' },
        { status: 502 }
      );
    }
    return NextResponse.json({ success: true, data: payload }, { status: response.status });
  } catch (error) {
    console.error(`agent access ${method} failed:`, error instanceof Error ? error.message : error);
    const message =
      error instanceof Error && error.message ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * Parse a JSON request body, or answer 400.
 *
 * @param request - The browser's request.
 * @returns The parsed body, or the 400 response that ends the request.
 */
export async function readJsonBody(request: Request): Promise<unknown | NextResponse> {
  try {
    return await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }
}

/**
 * Copy the named query parameters from a request URL into a query string.
 *
 * Only whitelisted names are forwarded, so a hand-made URL cannot reach a REST parameter this
 * surface does not use.
 *
 * @param url - The request URL.
 * @param names - The parameter names to forward.
 * @returns `?a=1&b=2`, or an empty string when none is present.
 */
export function forwardQuery(url: string, names: readonly string[]): string {
  const source = new URL(url).searchParams;
  const out = new URLSearchParams();
  for (const name of names) {
    const value = source.get(name);
    if (value !== null && value !== '') out.set(name, value);
  }
  const qs = out.toString();
  return qs ? `?${qs}` : '';
}
