/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/changelog.xml` — the project's public changelog as an
 * RSS 2.0 feed (CTG-3.2, #4476).
 *
 * Anonymous and cacheable: rows come from `getPublicChangelogsForProject` (public gate applied in
 * SQL, private `error` column never selected), rendering is the pure `lib/feed/changelog-feed`
 * layer, and a content-addressed ETag + `If-None-Match` → 304 spares a polling reader the body
 * until the changelog actually changes.
 */

import {
  getPublicChangelogsForProject,
  getPublicProjectBySlug,
} from '../../../../../../lib/db/helper';
import {
  buildProjectFeedMeta,
  feedETag,
  feedUpdatedFromRows,
  ifNoneMatchMatches,
  renderChangelogRss,
} from '../../../../../../lib/feed/changelog-feed';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ tenantSlug: string; projectSlug: string }> }
): Promise<Response> {
  const { tenantSlug, projectSlug } = await params;
  const project = await getPublicProjectBySlug(tenantSlug, projectSlug);
  if (!project) {
    return new Response('Not found', { status: 404 });
  }

  const rows = await getPublicChangelogsForProject(tenantSlug, projectSlug);
  const meta = buildProjectFeedMeta(
    request.url,
    process.env.NEXT_PUBLIC_BASE_PATH ?? '',
    project.name,
    tenantSlug,
    projectSlug,
    'xml',
    feedUpdatedFromRows(rows)
  );
  const body = renderChangelogRss(meta, rows);
  const etag = feedETag(body);
  const headers = {
    'Content-Type': 'application/rss+xml; charset=utf-8',
    ETag: etag,
    'Cache-Control': 'public, max-age=300',
  };
  if (ifNoneMatchMatches(request.headers.get('if-none-match'), etag)) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(body, { headers });
}
