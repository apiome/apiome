/**
 * apiome-ui middleware
 *
 * Single chokepoint that disables git-like API routes when
 * `FEATURE_GITLIKE` is off. The corresponding UI is already gated, so this
 * layer exists to ensure that direct fetches (or any straggling caller we
 * missed) cannot trigger commit / publish / branch / merge / rollback /
 * tag / change-report flows.
 *
 * - When `FEATURE_GITLIKE === true`: pass-through.
 * - When `FEATURE_GITLIKE === false`: respond `404 Not Found` for any
 *   git-like API path. Read-only and non-git-like routes (auth, classes,
 *   properties, paths, primitives, snapshot, sso, projects, migrations,
 *   `GET /api/versions`, `GET|PUT /api/versions/[id]`, sunset-timeline,
 *   etc.) are passed through unchanged.
 *
 * To re-enable git-like APIs, flip `FEATURE_GITLIKE` in `lib/feature-flags.ts`.
 */
import { NextResponse, type NextRequest } from 'next/server';
import { FEATURE_GITLIKE } from '@lib/feature-flags';
import { isGitlikePath } from '@lib/gitlike-route-guard';

export function middleware(request: NextRequest): NextResponse {
  if (FEATURE_GITLIKE) return NextResponse.next();

  const { pathname } = request.nextUrl;
  if (!pathname.startsWith('/api/')) return NextResponse.next();

  if (isGitlikePath(pathname, request.method.toUpperCase())) {
    return NextResponse.json(
      {
        success: false,
        error: 'Not found',
        detail: 'Git-like features are disabled in this build.',
      },
      { status: 404 }
    );
  }

  return NextResponse.next();
}

/**
 * Limit middleware execution to API routes; static assets, pages, and
 * `_next` internals don't need this guard. (Next.js requires `matcher` to
 * be statically analyzable — keep it as a top-level array literal.)
 */
export const config = {
  matcher: ['/api/:path*'],
};
