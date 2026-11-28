/**
 * The broker address of the signed-in workspace — PFX-8.15 (#7312), **Settings → CI and commit
 * statuses → Broker address**.
 *
 * `GET` answers `{ broker_base_url }` — what a pipeline sets as `PACT_BROKER_BASE_URL` — built from REST's
 * public base (`NEXT_PUBLIC_REST_API_BASE_URL`) and the workspace's handle. It reads nothing from REST
 * and carries no credential.
 */

import { NextResponse } from 'next/server';
import { resolveConnectorTenant } from '@lib/connectors-proxy';
import { PUBLIC_REST_BASE_URL } from '@lib/pact-badges';
import { brokerBaseUrl } from '@lib/pact-contract-settings';

export const dynamic = 'force-dynamic';

export async function GET() {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return NextResponse.json({ broker_base_url: brokerBaseUrl(PUBLIC_REST_BASE_URL, resolved.slug) });
}
