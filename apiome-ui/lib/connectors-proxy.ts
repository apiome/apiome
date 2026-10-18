/**
 * Shared forwarding for the `/api/connectors/*` proxy routes (CDG-1.6, #5957).
 *
 * The shadow-API report and its row actions talk to one REST surface with the same auth and the
 * same error contract, so the forwarding lives here once. Permissions (`imports:view` to read,
 * `imports:edit` to act) are REST's: duplicating them here would only create a second place to get
 * them wrong.
 */

import { NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import { getAuthenticatedTenantContext, type SessionUser } from '@lib/primitives-api-proxy';
import { restErrorMessage } from '@lib/rest-error-message';

export { CONNECTOR_ITEM_ACTIONS, isConnectorItemAction, type ConnectorItemAction } from '@lib/connector-item-actions';

/**
 * Resolve the caller's tenant, or the response explaining why we cannot.
 *
 * @returns The session user and tenant slug, or a ready-to-return error response.
 */
export async function resolveConnectorTenant(): Promise<
  { user: SessionUser; slug: string } | { error: NextResponse }
> {
  const context = await getAuthenticatedTenantContext();
  if (!context.ok) {
    return {
      error: NextResponse.json({ success: false, error: context.error }, { status: context.status }),
    };
  }
  return { user: context.user, slug: context.tenantSlug };
}

/**
 * The REST URL of one path below `/v1/tenants/{slug}`.
 *
 * @param slug - Tenant slug.
 * @param path - Path below the tenant, e.g. `shadow-report` or `connectors/{id}/items/{itemId}/link`.
 */
export function tenantUrl(slug: string, path: string): string {
  return `${REST_API_BASE_URL}/tenants/${encodeURIComponent(slug)}/${path}`;
}

/**
 * Forward one request to REST and pass its answer through.
 *
 * A success is returned as REST sent it. A failure keeps REST's status — the page tells a 403 (no
 * permission) from a 404 (the row or the target is gone) from a 409 (a sync is already running) —
 * with REST's message under `error`.
 *
 * @param url - The REST URL to call.
 * @param init - Method, the authenticated user, an optional JSON body, and the message to show when
 *   apiome-rest cannot be reached (other proxies — teams, owners — reuse this forwarder).
 * @returns The response to hand back to the browser.
 */
export async function forwardConnectorRequest(
  url: string,
  init: { method: string; user: SessionUser; body?: unknown; unavailable?: string }
): Promise<NextResponse> {
  try {
    const rest = await fetch(url, {
      method: init.method,
      headers: {
        ...createRestAuthHeaders(init.user),
        ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
      cache: 'no-store',
    });
    const text = await rest.text();
    let parsed: unknown;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      parsed = { raw: text };
    }
    if (rest.ok) return NextResponse.json(parsed);
    return NextResponse.json(
      { success: false, error: restErrorMessage(parsed) },
      { status: rest.status >= 400 ? rest.status : 502 }
    );
  } catch {
    return NextResponse.json(
      {
        success: false,
        error:
          init.unavailable ?? 'The connector API is unavailable (apiome-rest not reachable). Try again shortly.',
      },
      { status: 503 }
    );
  }
}
