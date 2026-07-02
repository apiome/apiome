/**
 * Pure helpers for classifying API requests as git-like or not.
 *
 * Lives in `lib/` (no `next/server` import) so it can be unit-tested without
 * pulling in the Next.js Edge runtime. The middleware (`src/middleware.ts`)
 * is the sole production caller.
 */

/**
 * Always-blocked git-like API path prefixes (any HTTP method).
 *
 * `publish` / `unpublish` are intentionally NOT in this list — they are
 * release-management concepts (mark a revision immutable/public), not
 * git-style push, so they remain enabled.
 */
const ALWAYS_BLOCKED_PATTERNS: RegExp[] = [
  /^\/api\/versions\/fork(\/|$)/,
  /^\/api\/versions\/[^/]+\/(freeze-schema|draft-lock|change-report)(\/|$)/,
  /^\/api\/projects\/[^/]+\/(version-branches|version-tags|compatibility|change-report-template-default)(\/|$)/,
  /^\/api\/projects\/[^/]+\/versions\/[^/]+\/revision-lock(\/|$)/,
  /^\/api\/change-report-template-versions(\/|$)/,
  /^\/api\/change-report-template-default(\/|$)/,
];

/** Method-aware blocks: matcher → set of HTTP methods that are forbidden. */
const METHOD_BLOCKS: Array<{ test: (pathname: string) => boolean; methods: Set<string> }> = [
  /* `/api/versions` (collection): POST creates a new revision (commit). GET
     stays so the version selector and dashboard list keep working. */
  {
    test: (p) => p === '/api/versions' || p === '/api/versions/',
    methods: new Set(['POST']),
  },
  /* `/api/versions/[id]`: DELETE hard-removes a revision. GET (read) and
     PUT (edit revision metadata via the still-enabled Edit dialog) remain. */
  {
    test: (p) => /^\/api\/versions\/[^/]+\/?$/.test(p) && p !== '/api/versions/sunset-timeline',
    methods: new Set(['DELETE']),
  },
];

/**
 * Returns true when the request targets a git-like API surface that should
 * be 404'd while `FEATURE_GITLIKE` is off.
 *
 * Method should be the uppercase HTTP verb (e.g. 'GET', 'POST').
 */
export function isGitlikePath(pathname: string, method: string): boolean {
  /* `/api/versions/sunset-timeline` is the read-only sunset list and must
     never be classified as git-like, even though it lives under `/api/versions`. */
  if (
    pathname === '/api/versions/sunset-timeline' ||
    pathname.startsWith('/api/versions/sunset-timeline/')
  ) {
    return false;
  }

  for (const re of ALWAYS_BLOCKED_PATTERNS) {
    if (re.test(pathname)) return true;
  }
  for (const block of METHOD_BLOCKS) {
    if (block.test(pathname) && block.methods.has(method)) return true;
  }
  return false;
}
