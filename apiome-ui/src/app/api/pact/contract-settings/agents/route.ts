/**
 * Save the four agent switches (`read`, `draft`, `publish`, `record`) — PFX-8.15 (#7312), **Settings → Agents**.
 *
 * `PUT` takes the switches as booleans (`checkSwitchesBody`; an unknown key or a non-boolean is a 400
 * naming it) and proxies `PUT /v1/tenants/{slug}/pact-contract-settings/agents`. Permissions
 * (`pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { AGENT_KEYS, AGENTS_PROXY_PATH, checkSwitchesBody } from '@lib/pact-contract-settings';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function PUT(request: NextRequest) {
  const checked = checkSwitchesBody(await request.json().catch(() => null), AGENT_KEYS);
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(AGENTS_PROXY_PATH, 'PUT', checked.body);
}
