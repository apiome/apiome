import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestGet,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

/** GET /api/types/namespaces — type-registry namespace collections (#3467). */
export async function GET() {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { data, error, status } = await proxyRestGet(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/namespaces`
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, namespaces: data });
  } catch (error) {
    console.error('Error fetching type namespaces:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}

/** POST /api/types/namespaces — create a tenant namespace (Namespaces UI #3471 / API #3451). */
export async function POST(request: NextRequest) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const body = await request.json();

    const { data, error, status } = await proxyRestPost(
      ctx.user,
      `/types/${encodeURIComponent(ctx.tenantSlug)}/namespaces`,
      body
    );

    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }

    return NextResponse.json({ success: true, namespace: data });
  } catch (error) {
    console.error('Error creating type namespace:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
