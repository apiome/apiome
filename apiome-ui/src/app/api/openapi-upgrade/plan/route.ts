/**
 * Plan an OpenAPI version upgrade (no write) — COA-2.6 (#7049).
 *
 * Proxies `POST /v1/openapi-upgrade/{slug}/plan` (see `@lib/openapi-upgrade-proxy`).
 */

import { NextRequest } from 'next/server';
import { forwardOpenapiUpgrade } from '@lib/openapi-upgrade-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/openapi-upgrade/plan`. */
export async function POST(request: NextRequest) {
  return forwardOpenapiUpgrade(request, 'plan');
}
