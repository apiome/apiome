/**
 * The tenant's external `$ref` policy — COA-2.8 (#7051).
 *
 * `GET /api/external-ref-policy` reads it (any member); `PUT` with `{mode, allowlist}` changes it
 * (tenant administrators only — apiome-rest enforces that and audits the change). Both forward to
 * `/v1/tenants/{tenant}/governance/external-ref-policy`.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardReferences, readReferencesBody } from '@lib/project-references-proxy';

export const dynamic = 'force-dynamic';

/** The REST path for the session's tenant. */
const policyPath = (tenant: string) => `/tenants/${encodeURIComponent(tenant)}/governance/external-ref-policy`;

/**
 * Read the policy.
 *
 * @returns `{success, data: {mode, allowlist, resolution_allowed, fetches, can_edit}}`.
 */
export async function GET(): Promise<NextResponse> {
  return forwardReferences('GET', policyPath);
}

/**
 * Change the policy.
 *
 * @returns `{success, data: policy}` or `{success: false, error, code}`.
 */
export async function PUT(request: NextRequest): Promise<NextResponse> {
  const body = await readReferencesBody(request);
  if (body instanceof NextResponse) return body;
  return forwardReferences('PUT', policyPath, body);
}
