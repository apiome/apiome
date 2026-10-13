import { NextRequest, NextResponse } from 'next/server';
import {
  REST_API_BASE_URL,
  handleIdentityRestResponse,
  refuseCrossSiteWrite,
  resolveIdentityProxyContext,
} from '../_proxy';

/**
 * Link two projects into one cross-format identity group, for the session's active tenant.
 *
 * Same-origin only (#4963). The body's `projectId` / `relatedProjectId` are forwarded as sent;
 * apiome-rest refuses (404) any id that is not a project of the session's tenant.
 */

export async function POST(request: NextRequest) {
  try {
    const refusal = refuseCrossSiteWrite(request.headers);
    if (refusal) {
      return NextResponse.json({ success: false, error: refusal.error }, { status: refusal.status });
    }
    const ctx = await resolveIdentityProxyContext();
    if ('error' in ctx) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const body = await request.json();
    const response = await fetch(`${REST_API_BASE_URL}/identity/${ctx.tenantSlug}/link`, {
      method: 'POST',
      headers: ctx.headers,
      body: JSON.stringify(body),
    });
    const { data, error, status } = await handleIdentityRestResponse(response, 'Link failed');
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/**
 * Remove a project from its identity group, for the session's active tenant.
 *
 * Same-origin only (#4963); the body's ids are scoped to the tenant by apiome-rest, as for POST.
 */
export async function DELETE(request: NextRequest) {
  try {
    const refusal = refuseCrossSiteWrite(request.headers);
    if (refusal) {
      return NextResponse.json({ success: false, error: refusal.error }, { status: refusal.status });
    }
    const ctx = await resolveIdentityProxyContext();
    if ('error' in ctx) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const body = await request.json();
    const response = await fetch(`${REST_API_BASE_URL}/identity/${ctx.tenantSlug}/link`, {
      method: 'DELETE',
      headers: ctx.headers,
      body: JSON.stringify(body),
    });
    const { data, error, status } = await handleIdentityRestResponse(response, 'Unlink failed');
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, ...(data as Record<string, unknown>) });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
