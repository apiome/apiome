/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/changelog.json` — the project's public changelog as a
 * JSON Feed 1.1 document (CTG-3.2, #4476). The JSON sibling of `changelog.xml/route.ts`; same
 * public gate, ETag/304 handling, and cache policy.
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
  renderChangelogJsonFeed,
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
    'json',
    feedUpdatedFromRows(rows)
  );
  const body = JSON.stringify(renderChangelogJsonFeed(meta, rows));
  const etag = feedETag(body);
  const headers = {
    'Content-Type': 'application/feed+json; charset=utf-8',
    ETag: etag,
    'Cache-Control': 'public, max-age=300',
  };
  if (ifNoneMatchMatches(request.headers.get('if-none-match'), etag)) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(body, { headers });
}
