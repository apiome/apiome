/**
 * Server-side forwarders for the admin console's Document store page (COA-5.9, #7085).
 *
 * The page cannot call apiome-rest directly (different origin; the signed `admin_session` cookie
 * lives on the UI domain), so its Next.js API routes (`src/app/api/admin/document-store`) forward
 * here. Like the sign-up policy proxy, each forwarder presents the verified session upstream —
 * apiome-rest verifies it again — relays the upstream status and body verbatim, and never throws.
 * The UI never talks to the bucket: REST runs every check.
 *
 * Server-only: import from API routes / server code, never from a client component.
 */
import { forwardToAdminRest, type AdminProviderProxyResult } from './admin-provider-config-proxy';

/**
 * Read the document store's settings, health and usage (forwards `GET /v1/admin/document-store`).
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body (a `DocumentStoreStatus` on 200).
 */
export async function proxyGetDocumentStore(
  adminSessionToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AdminProviderProxyResult> {
  return forwardToAdminRest('/document-store', { method: 'GET' }, adminSessionToken, fetchImpl);
}

/**
 * Run the connection test: write, read back and delete a probe object
 * (forwards `POST /v1/admin/document-store/test`).
 *
 * @param adminSessionToken The verified signed admin-session token.
 * @param fetchImpl Fetch implementation (injectable for tests).
 * @returns The upstream status and body (a `DocumentStoreProbeResult` on 200).
 */
export async function proxyTestDocumentStore(
  adminSessionToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AdminProviderProxyResult> {
  return forwardToAdminRest('/document-store/test', { method: 'POST' }, adminSessionToken, fetchImpl);
}
