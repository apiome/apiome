/**
 * The server side of the Badges panel's preview — PFX-8.11 (#7308).
 *
 * Reads a public pact badge as an anonymous caller would — the README's reader — from REST's
 * `GET /v1/browse/tenants/{tenant}/projects/{project}/pact-badges/…/badge.svg` and its
 * `shields.json` twin, in the signed-in user's workspace, and answers `{ tenant, status, svg }`.
 * The preview is then the very SVG REST serves. REST's uniform `404` (a private project, a
 * pacticipant not bound to it) passes through as a 404 with its message.
 */

import { NextResponse } from 'next/server';
import { resolveConnectorTenant } from '@lib/connectors-proxy';
import { getRestApiBaseUrl } from '@lib/rest-auth';
import { badgePath, statusFromShields, type BadgeAnswer, type BadgeTarget } from '@lib/pact-badges';
import { PACT_UNAVAILABLE, pactError } from '@lib/pact-proxy';

/** What the browser is told when REST serves no badge. */
export const NO_BADGE = 'No badge is served for this: the project is not public, or nothing named here is bound to it.';

/**
 * Read one badge anonymously and answer with its SVG and state.
 *
 * @param project - The public project's slug (already checked).
 * @param target - What the badge is for (already checked).
 * @returns `{ tenant, status, svg }`, a 404 when REST serves none, a 503 when REST is unreachable.
 */
export async function forwardPactBadge(project: string, target: BadgeTarget): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const base = getRestApiBaseUrl();
  try {
    const [svg, shields] = await Promise.all([
      fetch(`${base}${badgePath(resolved.slug, project, target, 'badge.svg')}`, { cache: 'no-store' }),
      fetch(`${base}${badgePath(resolved.slug, project, target, 'shields.json')}`, { cache: 'no-store' }),
    ]);
    if (svg.status === 404 || shields.status === 404) return pactError(404, NO_BADGE);
    if (!svg.ok || !shields.ok) return pactError(502, `REST answered ${svg.ok ? shields.status : svg.status} for the badge.`);
    const answer: BadgeAnswer = {
      tenant: resolved.slug,
      status: statusFromShields(await shields.json().catch(() => null)),
      svg: await svg.text(),
    };
    return NextResponse.json(answer);
  } catch {
    return pactError(503, PACT_UNAVAILABLE);
  }
}
