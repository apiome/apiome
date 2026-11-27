/**
 * Upload verification results — PFX-8.9 (#7306), the screen for `apiome pact
 * publish-verification-results`.
 *
 * `POST` takes the dialog's JSON — provider, consumer, pact version, provider version, branch, build
 * URL, tags, format, verifier, and the report's text with its media type — refuses, naming it, any
 * field it does not know, a mistyped or oversized one, and sends the report itself to
 * `POST …/pact-version/{sha}/external-verification-results` as the signed-in user. REST reads it
 * (Pact verifier JSON, JUnit, Schemathesis, Newman, Dredd) and refuses an unreadable report with its
 * reason; nothing is recorded then. Tenancy and `pacts:create` are REST's.
 */

import { NextRequest } from 'next/server';
import { pickUpload } from '@lib/pact-verify-upload';
import { forwardReportUpload } from '@lib/pact-verify-live-proxy';
import { pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickUpload(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardReportUpload(picked.upload);
}
