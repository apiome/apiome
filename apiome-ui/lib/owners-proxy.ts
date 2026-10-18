/**
 * Shared forwarding for the `/api/teams/*` and `/api/owners/*` proxy routes — CDG-2.4 (#5963).
 *
 * Auth and forwarding only: the `teams:view` and per-kind `edit` permissions are apiome-rest's.
 * Every path segment a route puts into the upstream URL is checked here first, so a crafted slug or
 * kind can never address another REST path.
 */

import type { NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { OWNER_ENTITY_KINDS, sanitizeTeamParam } from '@lib/owners';

export { resolveConnectorTenant as resolveTenant, tenantUrl };

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The teams API is unavailable (apiome-rest not reachable). Try again shortly.';

/** An entity id: a UUID, as every owned kind uses. */
const ENTITY_ID = /^[0-9a-fA-F-]{36}$/;

/**
 * Whether a path segment is a team slug.
 *
 * @param slug - The segment.
 * @returns True when it is slug-shaped.
 */
export function isTeamSlug(slug: string): boolean {
  return sanitizeTeamParam(slug) === slug;
}

/**
 * Whether two path segments name an ownable entity.
 *
 * @param kind - The kind segment.
 * @param id - The id segment.
 * @returns True for a known kind and a UUID.
 */
export function isEntityRef(kind: string, id: string): boolean {
  return (OWNER_ENTITY_KINDS as readonly string[]).includes(kind) && ENTITY_ID.test(id);
}

/**
 * Forward one teams/owners request.
 *
 * @param url - The REST URL.
 * @param init - Method, user and optional body.
 * @returns REST's answer, passed through (see `forwardConnectorRequest`).
 */
export function forwardOwnersRequest(
  url: string,
  init: Omit<Parameters<typeof forwardConnectorRequest>[1], 'unavailable'>
): Promise<NextResponse> {
  return forwardConnectorRequest(url, { ...init, unavailable: UNAVAILABLE });
}
