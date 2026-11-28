/**
 * Open the can-i-deploy / record-deployment pull requests — PFX-8.20 (#7317), **Set up contracts →
 * Gate deploys and tell people**.
 *
 * `POST { repositories: [{ repository_id, pacticipant }], environment, can_i_deploy?, record_deployment?,
 * preview? }` (`checkPullRequestsBody`) forwards `POST /v1/tenants/{slug}/pact-setup/github/pull-requests`.
 * With `preview` GitHub is not called and REST only answers with the workflow each pull request would
 * add. REST answers per repository — `opened`, `exists`, `preview`, or `skipped` with the reason, always
 * with the workflow's text — and owns `pacts:delete` and tenant scoping.
 */

import { NextRequest } from 'next/server';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';
import { SETUP_PULL_REQUESTS_PROXY_PATH, checkPullRequestsBody } from '@lib/pact-setup';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const checked = checkPullRequestsBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(SETUP_PULL_REQUESTS_PROXY_PATH, 'POST', checked.body);
}
