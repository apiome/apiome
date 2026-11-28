/**
 * Migration runs — PFX-8.16 (#7313), the **Migration wizard** (`/ade/dashboard/pacts/migrate`).
 *
 * `GET` proxies `GET /v1/tenants/{slug}/pact-migration/runs` (no parameters: any is a 400 naming it):
 * the workspace's runs, newest first, and whether the viewer may run one — the **Past migrations**
 * drawer. `POST` starts a run (a dry run, or a copy); the body is checked by `checkStartBody`
 * (`source`, `token` or `username` / `password`, `mode`, `options`; anything else is a 400 naming it).
 *
 * The source's credentials pass through to REST for this run only: neither this proxy nor REST stores
 * or logs them. Permissions (`pacts:view`; `pacts:create` and `pacts:edit` to start), tenant scoping
 * and the one-run-at-a-time rule are REST's.
 */

import { NextRequest } from 'next/server';
import { MIGRATION_PROXY_PATH, checkStartBody } from '@lib/pact-migration';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = [...request.nextUrl.searchParams.keys()];
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the migrations list takes none.`);
  return forwardPactRead(`${MIGRATION_PROXY_PATH}/runs`);
}

export async function POST(request: NextRequest) {
  const checked = checkStartBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(`${MIGRATION_PROXY_PATH}/runs`, 'POST', checked.body);
}
