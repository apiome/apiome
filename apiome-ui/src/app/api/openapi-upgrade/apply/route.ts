/**
 * Apply a reviewed OpenAPI upgrade as a new version — COA-2.6 (#7049).
 *
 * Proxies `POST /v1/openapi-upgrade/{slug}/apply` (see `@lib/openapi-upgrade-proxy`).
 */

import { NextRequest } from 'next/server';
import { forwardOpenapiUpgrade } from '@lib/openapi-upgrade-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/openapi-upgrade/apply`. */
export async function POST(request: NextRequest) {
  return forwardOpenapiUpgrade(request, 'apply');
}
