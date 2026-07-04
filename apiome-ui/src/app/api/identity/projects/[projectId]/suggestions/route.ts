import { NextResponse } from 'next/server';
import {
  REST_API_BASE_URL,
  handleIdentityRestResponse,
  resolveIdentityProxyContext,
} from '../../../_proxy';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ projectId: string }> },
) {
  try {
    const { projectId } = await params;
    const ctx = await resolveIdentityProxyContext();
    if ('error' in ctx) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const response = await fetch(
      `${REST_API_BASE_URL}/identity/${ctx.tenantSlug}/projects/${encodeURIComponent(projectId)}/suggestions`,
      { method: 'GET', headers: ctx.headers },
    );
    const { data, error, status } = await handleIdentityRestResponse(
      response,
      'Failed to fetch suggestions',
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, suggestions: data });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
