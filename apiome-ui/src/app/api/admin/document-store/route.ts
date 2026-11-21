/**
 * Admin document store proxy (COA-5.9, #7085).
 *
 * `GET /api/admin/document-store` relays the document store's settings, health and usage from
 * apiome-rest (`GET /v1/admin/document-store`) to the admin console's **Document store** page. It
 * verifies the signed `admin_session` cookie first; apiome-rest verifies the same token again, so
 * the proxy adds no authority of its own. The settings are read-only: the REST server's
 * environment is the only place they are set.
 */
import { NextResponse } from 'next/server';
import { requireAdminSession } from '../signup-policy/admin-session-gate';
import { proxyGetDocumentStore } from '@lib/auth/admin-document-store-proxy';

export async function GET() {
  const session = await requireAdminSession();
  if ('response' in session) return session.response;

  const result = await proxyGetDocumentStore(session.token);
  return NextResponse.json(result.body, { status: result.status, headers: { 'Cache-Control': 'no-store' } });
}
