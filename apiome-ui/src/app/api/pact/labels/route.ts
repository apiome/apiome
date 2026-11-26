/**
 * The workspace's pacticipant labels — PFX-5.1 (#6945).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipant-labels?limit=100` (the first page, by name) for the
 * **Pacticipants** label filter. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { LABELS_PROXY_PATH } from '@lib/pact-pacticipants';
import { forwardPactRead } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  return forwardPactRead(LABELS_PROXY_PATH);
}
