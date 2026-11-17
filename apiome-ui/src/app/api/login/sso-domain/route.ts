/**
 * Does this email sign in with single sign-on? (EID-1.2, #5012)
 *
 *   POST /api/login/sso-domain   { "email": "ada@acme.com" }   ->   { "sso": true }
 *
 * The sign-in page asks while the reader types, so an address in a workspace's **verified** domain
 * of an **enabled** identity provider is offered only "Continue with SSO". The answer comes from
 * the same routable set Better Auth's SSO plugin is configured with (`resolveSsoProviders`), so
 * the page can never offer a route the plugin would refuse — and an unverified or disabled
 * provider's domain answers `false` like any other.
 *
 * Unauthenticated by necessity (it serves the sign-in page). It reveals only what starting an SSO
 * sign-in for that address already reveals: whether a provider covers the domain. No provider
 * name, id or domain list is returned. Never throws: any failure answers `false`, which leaves the
 * password path in place.
 */

import { NextRequest, NextResponse } from 'next/server';

import { resolveSsoProviders } from '@lib/auth/sso-provider-resolver';
import { emailDomainForSso } from '@lib/workspace-sso';

export const dynamic = 'force-dynamic';

/** The longest address worth reading (RFC 5321's limit). */
const MAX_EMAIL_LENGTH = 254;

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json().catch(() => null)) as { email?: unknown } | null;
    const email = typeof body?.email === 'string' ? body.email.slice(0, MAX_EMAIL_LENGTH) : '';
    const domain = emailDomainForSso(email);
    if (!domain) return NextResponse.json({ sso: false });
    const { providers } = await resolveSsoProviders();
    return NextResponse.json({ sso: providers.some((provider) => provider.domains.includes(domain)) });
  } catch {
    return NextResponse.json({ sso: false });
  }
}
