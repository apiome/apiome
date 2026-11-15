/**
 * Server-side reader session read — PCX-1.1 (#5889).
 *
 * The layouts and pages that show who is signed in call {@link getReaderSession}. It reads the
 * `HttpOnly` cookie (so it only works in Server Components and route handlers) and asks apiome-rest
 * whether the session is still live — revocation takes effect on the next page load, because nothing
 * here is cached.
 */

import { cookies } from 'next/headers';

import { fetchReader, serverRestBase, type ReaderProfile } from '../../../lib/portal/api';
import { parseReaderCookie, READER_SESSION_COOKIE } from '../../../lib/portal/session';

/** A live reader session. */
export interface ReaderSession {
  /** The tenant the session is bound to. */
  tenantSlug: string;
  /** The reader, as `GET …/auth/me` returns them. */
  reader: ReaderProfile;
}

/**
 * Read the signed-in reader, if any.
 *
 * @param tenantSlug - When given, only a session for this tenant counts — a reader signed in to one
 *   portal is not signed in to another.
 * @returns The live session, or null when there is none, it belongs to another tenant, or apiome-rest
 *   no longer accepts it.
 */
export async function getReaderSession(tenantSlug?: string): Promise<ReaderSession | null> {
  const store = await cookies();
  const parsed = parseReaderCookie(store.get(READER_SESSION_COOKIE)?.value);
  if (!parsed || (tenantSlug && parsed.tenantSlug !== tenantSlug)) return null;
  const reader = await fetchReader(serverRestBase(process.env), parsed.tenantSlug, parsed.token);
  return reader ? { tenantSlug: parsed.tenantSlug, reader } : null;
}

/**
 * Prefix a Browse path with `NEXT_PUBLIC_BASE_PATH` for a plain HTML `<form action>`, which (unlike
 * `<Link>` and the router) Next does not prefix itself.
 *
 * @param path - A path starting with `/`.
 * @returns The path under the base path.
 */
export function withBasePath(path: string): string {
  return `${(process.env.NEXT_PUBLIC_BASE_PATH || '').replace(/\/+$/, '')}${path}`;
}
