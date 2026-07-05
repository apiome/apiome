import { NextRequest, NextResponse } from 'next/server';
import {
  REST_API_BASE_URL,
  handleIdentityRestResponse,
  resolveIdentityProxyContext,
} from '../_proxy';

export async function POST(request: NextRequest) {
  try {
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

export async function DELETE(request: NextRequest) {
  try {
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
