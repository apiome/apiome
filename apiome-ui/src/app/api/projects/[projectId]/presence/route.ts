/**
 * Proxy for a project's presence and element soft locks — COL-4.1 (#4525).
 *
 * The browser cannot reach apiome-rest directly (the bearer is signed server-side), so the tab's
 * heartbeats and lock actions come through here. The tenant is decided from the session; apiome-rest
 * enforces `projects:view` and owns every rule, so this route adds none.
 *
 * - `GET`  → the project's snapshot (viewers and locks), without announcing the caller.
 * - `POST` → `{action, session_id, view?, held?, element_key?}`; see {@link PresenceAction}.
 */

import { NextRequest, NextResponse } from 'next/server';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';
import {
  resolveCommentThreadsAuth,
  restErrorMessage,
  type CommentThreadsAuth,
} from '../comment-threads/comment-threads-proxy';

const ACTIONS = ['heartbeat', 'leave', 'lock', 'unlock', 'request_takeover', 'take_over'] as const;

/**
 * The apiome-rest request an action maps to.
 *
 * @param action - The BFF action.
 * @param base - The project's presence URL.
 * @param body - The parsed browser body.
 * @returns Method, URL and JSON body for apiome-rest.
 */
function restCall(
  action: (typeof ACTIONS)[number],
  base: string,
  body: Record<string, unknown>
): { method: string; url: string; json?: unknown } {
  const session = encodeURIComponent(String(body.session_id ?? ''));
  const key = encodeURIComponent(String(body.element_key ?? '')).replace(/%3A/gi, ':');
  switch (action) {
    case 'heartbeat':
      return { method: 'POST', url: `${base}/heartbeat`, json: { session_id: body.session_id, view: body.view, held: body.held ?? [] } };
    case 'leave':
      return { method: 'POST', url: `${base}/leave`, json: { session_id: body.session_id } };
    case 'lock':
      return { method: 'PUT', url: `${base}/locks/${key}?session_id=${session}` };
    case 'unlock':
      return { method: 'DELETE', url: `${base}/locks/${key}?session_id=${session}` };
    case 'request_takeover':
      return { method: 'POST', url: `${base}/request-takeover/${key}?session_id=${session}` };
    default:
      return { method: 'POST', url: `${base}/take-over/${key}?session_id=${session}` };
  }
}

/**
 * Call apiome-rest and relay its answer.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @param call - The request to make.
 * @returns A `{success, ...snapshot}` or `{success: false, error, code}` response.
 */
async function relay(
  auth: CommentThreadsAuth,
  call: { method: string; url: string; json?: unknown }
): Promise<NextResponse> {
  const headers: Record<string, string> = { ...createRestAuthHeaders(auth.user) };
  if (call.json !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(call.url, {
    method: call.method,
    headers,
    body: call.json !== undefined ? JSON.stringify(call.json) : undefined,
  });
  if (response.status === 204) return NextResponse.json({ success: true });
  const raw = await response.text();
  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const code = (payload as { detail?: { code?: unknown } } | null)?.detail?.code;
    return NextResponse.json(
      { success: false, error: restErrorMessage(payload, 'Presence request failed'), code: typeof code === 'string' ? code : undefined },
      { status: response.status || 502 }
    );
  }
  return NextResponse.json({ success: true, ...(payload as Record<string, unknown>) });
}

/**
 * The project's presence base URL on apiome-rest.
 *
 * @param auth - The caller.
 * @param projectRef - The project id or slug.
 * @returns The absolute URL.
 */
function presenceBase(auth: CommentThreadsAuth, projectRef: string): string {
  return (
    `${REST_API_BASE_URL}/tenants/${encodeURIComponent(auth.tenantSlug)}` +
    `/projects/${encodeURIComponent(projectRef)}/presence`
  );
}

/** GET /api/projects/[projectId]/presence — the snapshot. */
export async function GET(_request: NextRequest, { params }: { params: Promise<{ projectId: string }> }) {
  try {
    const { projectId } = await params;
    const auth = await resolveCommentThreadsAuth();
    if (auth instanceof NextResponse) return auth;
    return await relay(auth, { method: 'GET', url: presenceBase(auth, projectId) });
  } catch (error) {
    console.error('project presence GET:', error);
    return NextResponse.json({ success: false, error: 'Internal server error' }, { status: 500 });
  }
}

/** POST /api/projects/[projectId]/presence — a heartbeat, leave, or lock action. */
export async function POST(request: NextRequest, { params }: { params: Promise<{ projectId: string }> }) {
  try {
    const { projectId } = await params;
    const auth = await resolveCommentThreadsAuth();
    if (auth instanceof NextResponse) return auth;
    const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
    const action = body?.action;
    if (!body || !ACTIONS.includes(action as (typeof ACTIONS)[number])) {
      return NextResponse.json({ success: false, error: 'Unknown presence action' }, { status: 400 });
    }
    return await relay(auth, restCall(action as (typeof ACTIONS)[number], presenceBase(auth, projectId), body));
  } catch (error) {
    console.error('project presence POST:', error);
    return NextResponse.json({ success: false, error: 'Internal server error' }, { status: 500 });
  }
}
