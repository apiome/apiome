import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, restErrorMessage } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

/** A runner tool key as the registry names them (`buf`, `tsp`, `asyncapi`). */
const TOOL_KEY = /^[a-z0-9][a-z0-9-]{0,63}$/;

/** The body fields REST accepts; anything else (an uploaded file, say) is dropped here. */
const FORWARDED_FIELDS = ['artifact', 'version', 'target', 'options', 'check', 'jobId'] as const;

/**
 * POST /api/export/verify/tool-checks/{tool} — run one of the target's toolchain checks on the
 * artifact under review and stream its console (MFX-44.6, #4372).
 *
 * Proxies REST `POST /v1/export/{tenant_slug}/verify/tool-checks/{tool}`. The body names the check
 * (`check: "lint"` for `buf lint`) and the same coordinates `/api/export/verify` takes, plus the
 * completed job's `jobId` when the Review step has one — the artifact itself is never uploaded.
 *
 * A successful answer is an NDJSON stream (`start`, `output`…, `result`) passed through **unbuffered**
 * so the console fills as the tool writes. A refusal (`404` undeclared check, `429` rate limit, `503`
 * not installed) comes back as the usual `{ success: false, error }` JSON with REST's status.
 */
export async function POST(request: NextRequest, { params }: { params: Promise<{ tool: string }> }) {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }

    const { tool } = await params;
    if (!TOOL_KEY.test(tool)) {
      return NextResponse.json({ success: false, error: 'Unknown toolchain' }, { status: 400 });
    }

    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json({ success: false, error: 'Missing request body' }, { status: 400 });
    }
    const forwarded: Record<string, unknown> = {};
    for (const field of FORWARDED_FIELDS) {
      if (field in body) forwarded[field] = (body as Record<string, unknown>)[field];
    }

    const upstream = await fetch(
      `${REST_API_BASE_URL}/export/${encodeURIComponent(ctx.tenantSlug)}/verify/tool-checks/${encodeURIComponent(tool)}`,
      {
        method: 'POST',
        headers: createRestAuthHeaders(ctx.user),
        cache: 'no-store',
        body: JSON.stringify(forwarded),
        // Closing the console (or leaving the page) stops the tool on the server.
        signal: request.signal,
      },
    );

    if (!upstream.ok || !upstream.body) {
      const data = await upstream.json().catch(() => null);
      const error = data ? restErrorMessage(data) : 'Toolchain check failed';
      return NextResponse.json({ success: false, error }, { status: upstream.status || 502 });
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        'Content-Type': 'application/x-ndjson',
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    console.error('Error running export toolchain check:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
