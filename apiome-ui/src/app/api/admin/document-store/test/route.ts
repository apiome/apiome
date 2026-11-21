/**
 * Admin document store connection test (COA-5.9, #7085).
 *
 * `POST /api/admin/document-store/test` relays to `POST /v1/admin/document-store/test`, where
 * apiome-rest writes, reads back and deletes a probe object and reports each step. The signed
 * `admin_session` cookie is verified here and again upstream.
 */
import { NextResponse } from 'next/server';
import { requireAdminSession } from '../../signup-policy/admin-session-gate';
import { proxyTestDocumentStore } from '@lib/auth/admin-document-store-proxy';

export async function POST() {
  const session = await requireAdminSession();
  if ('response' in session) return session.response;

  const result = await proxyTestDocumentStore(session.token);
  return NextResponse.json(result.body, { status: result.status, headers: { 'Cache-Control': 'no-store' } });
}
