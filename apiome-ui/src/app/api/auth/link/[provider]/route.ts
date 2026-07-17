import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../[...nextauth]/route';
import {
  AUTH_ERROR_CODES,
  LINKABLE_PROVIDERS,
} from '../../../../../../lib/auth/account-resolution';
import { isEntraIdConfigured } from '../../../../../../lib/auth/entra-provider';

/**
 * Whether this deployment can start a link flow for `provider` (OLO-2.2, #4194).
 *
 * The slug must belong to the linkable-provider vocabulary (`github` | `gitlab` | `azure` —
 * the same set V181 pins at the DB level), and `azure` additionally requires the Entra ID
 * env config: an unconfigured deployment registers no `azure` NextAuth provider at all
 * (OLO-2.1), so setting a linking-intent cookie for it would only dead-end at Microsoft.
 * GitHub/GitLab are always registered, so no config gate applies to them.
 *
 * @param provider The provider slug from the route path.
 * @returns True when a linking-intent cookie for this provider can lead to a working OAuth flow.
 */
function isProviderLinkable(provider: string): boolean {
  if (!LINKABLE_PROVIDERS.has(provider)) return false;
  if (provider === 'azure' && !isEntraIdConfigured()) return false;
  return true;
}

/**
 * API endpoint to set linking intent cookie before OAuth flow
 * This endpoint checks if user is logged in and sets a cookie to indicate linking intent
 *
 * Unknown or unconfigured providers are refused with 400 and the stable
 * `provider-not-configured` code (the structured auth error contract, OLO-1.5).
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ provider: string }> }
) {
  const session = await getServerSession(authOptions);

  if (!session || !(session.user as any)?.user_id) {
    return NextResponse.json(
      { error: 'Not authenticated' },
      { status: 401 }
    );
  }

  const { provider } = await params;

  if (!isProviderLinkable(provider)) {
    return NextResponse.json(
      {
        error: `Provider '${provider}' is not available for linking on this deployment`,
        code: AUTH_ERROR_CODES.PROVIDER_NOT_CONFIGURED,
      },
      { status: 400 }
    );
  }

  const userId = (session.user as any).user_id;

  // Create response with success status
  const response = NextResponse.json({
    success: true,
    provider,
    userId
  });

  // Set the linking intent cookie
  response.cookies.set('oauth_link_intent', JSON.stringify({
    userId,
    provider,
    timestamp: Date.now()
  }), {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    maxAge: 600, // 10 minutes
    path: '/',
    sameSite: 'lax' as const
  });

  return response;
}
