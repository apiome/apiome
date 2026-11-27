/**
 * The BFF side of the live run and the results upload (PFX-8.9, #7306).
 *
 * {@link forwardReportUpload} sends a checked report (`pickUpload`) to
 * `POST …/external-verification-results` as the request body itself, with its media type — the
 * one REST call of the Contracts BFF whose body is not JSON. REST reads the report and refuses an
 * unreadable one with its reason (`422 pact-verification-invalid`, pointer included); the refusal
 * is passed through and nothing is recorded. Tenancy and `pacts:create` are REST's.
 */

import { NextResponse } from 'next/server';
import { resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { createRestAuthHeaders } from '@lib/rest-auth';
import { restErrorMessage } from '@lib/rest-error-message';
import { PACT_UNAVAILABLE } from '@lib/pact-proxy';
import type { PickedUpload } from '@lib/pact-verify-upload';

/**
 * Forward one report upload as the signed-in user.
 *
 * @param upload - The checked upload: REST path below the tenant, the report and its media type.
 * @returns REST's stored result (`201` → `200`, with `ingestion`), or its refusal as
 *   `{ success: false, error, pointer? }` with REST's status.
 */
export async function forwardReportUpload(upload: PickedUpload): Promise<NextResponse> {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  try {
    const rest = await fetch(tenantUrl(resolved.slug, upload.path), {
      method: 'POST',
      headers: { ...createRestAuthHeaders(resolved.user), 'Content-Type': upload.contentType },
      body: upload.report,
      cache: 'no-store',
    });
    const text = await rest.text();
    let parsed: unknown;
    try {
      parsed = text ? JSON.parse(text) : {};
    } catch {
      parsed = { raw: text };
    }
    if (rest.ok) return NextResponse.json(parsed);
    const detail = (parsed as { detail?: unknown } | null)?.detail;
    const pointer =
      detail &&
      typeof detail === 'object' &&
      typeof (detail as { pointer?: unknown }).pointer === 'string'
        ? (detail as { pointer: string }).pointer
        : undefined;
    return NextResponse.json(
      {
        success: false,
        error: restErrorMessage(parsed),
        ...(pointer !== undefined ? { pointer } : {}),
      },
      { status: rest.status >= 400 ? rest.status : 502 },
    );
  } catch {
    return NextResponse.json({ success: false, error: PACT_UNAVAILABLE }, { status: 503 });
  }
}
