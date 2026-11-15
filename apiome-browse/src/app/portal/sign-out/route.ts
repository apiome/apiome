/**
 * `POST /portal/sign-out` — sign the reader out, PCX-1.1 (#5889).
 *
 * Revokes the session in apiome-rest (so it is refused from the next request on, on every device that
 * holds the cookie value) and clears the cookie, then returns to the tenant's page. Only a same-origin
 * post is accepted.
 */

import { NextResponse, type NextRequest } from 'next/server';

import { serverRestBase, signOutReader } from '../../../../lib/portal/api';
import {
  isSameOriginPost,
  parseReaderCookie,
  READER_SESSION_COOKIE,
  readerCookieOptions,
} from '../../../../lib/portal/session';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isSameOriginPost(request.headers.get('origin'), request.url)) {
    return new NextResponse('Forbidden', { status: 403 });
  }
  const session = parseReaderCookie(request.cookies.get(READER_SESSION_COOKIE)?.value);
  if (session) {
    await signOutReader(serverRestBase(process.env), session.tenantSlug, session.token);
  }

  const url = request.nextUrl.clone();
  url.pathname = session ? `/tenant/${session.tenantSlug}` : '/';
  url.search = '';
  const response = NextResponse.redirect(url, 303);
  response.cookies.set(
    READER_SESSION_COOKIE,
    '',
    readerCookieOptions(process.env.NEXT_PUBLIC_BASE_PATH, new Date(0), process.env.NODE_ENV === 'production'),
  );
  return response;
}
