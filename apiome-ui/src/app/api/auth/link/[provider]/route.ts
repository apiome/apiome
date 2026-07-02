import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '../../[...nextauth]/route';

/**
 * API endpoint to set linking intent cookie before OAuth flow
 * This endpoint checks if user is logged in and sets a cookie to indicate linking intent
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

