/**
 * `POST /portal/auth/session` — exchange a magic-link token for a reader session, PCX-1.1 (#5889).
 *
 * Posted by the **Continue** button on `/portal/auth/exchange`. On success the session token goes into
 * the `HttpOnly` reader cookie (it never reaches page scripts) and the reader is sent to where the link
 * asked to land. On a refusal the reader is sent to `/portal/auth/error`, which names the reason —
 * expired, already used, or not valid — rather than silently landing on a public page.
 *
 * Only a same-origin post is accepted, so another site cannot sign a visitor in as someone else.
 */

import { NextResponse, type NextRequest } from 'next/server';

import { exchangeToken, serverRestBase } from '../../../../../lib/portal/api';
import {
  encodeReaderCookie,
  isSameOriginPost,
  isTenantSlug,
  READER_SESSION_COOKIE,
  readerCookieOptions,
  safeReturnTo,
} from '../../../../../lib/portal/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Redirect (303, so the browser follows with a GET) to a Browse path under the base path.
 *
 * @param request - The inbound request; its `nextUrl` carries the base path.
 * @param path - The destination path, with an optional query string.
 * @returns The redirect response.
 */
function seeOther(request: NextRequest, path: string): NextResponse {
  const url = request.nextUrl.clone();
  const [pathname, search = ''] = path.split('?');
  url.pathname = pathname;
  url.search = search ? `?${search}` : '';
  url.hash = '';
  return NextResponse.redirect(url, 303);
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOriginPost(request.headers.get('origin'), request.url)) {
    return new NextResponse('Forbidden', { status: 403 });
  }
  const form = await request.formData();
  const tenant = String(form.get('tenant') ?? '');
  const token = String(form.get('token') ?? '');
  if (!isTenantSlug(tenant) || !token) {
    return seeOther(request, '/portal/auth/error?reason=invalid');
  }

  const outcome = await exchangeToken(serverRestBase(process.env), tenant, token, request.headers.get('user-agent'));
  if (!outcome.ok) {
    return seeOther(request, `/portal/auth/error?tenant=${tenant}&reason=${outcome.reason}`);
  }

  const response = seeOther(request, safeReturnTo(outcome.grant.return_to, `/tenant/${tenant}`));
  response.cookies.set(
    READER_SESSION_COOKIE,
    encodeReaderCookie(tenant, outcome.grant.session_token),
    readerCookieOptions(
      process.env.NEXT_PUBLIC_BASE_PATH,
      new Date(outcome.grant.expires_at),
      process.env.NODE_ENV === 'production',
    ),
  );
  return response;
}
