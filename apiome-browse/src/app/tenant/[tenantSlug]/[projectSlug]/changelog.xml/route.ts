/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/changelog.xml` — the project's public changelog as an
 * RSS 2.0 feed (CTG-3.2, #4476).
 *
 * Anonymous and cacheable. The request handling — the public gate, the ETag and
 * `If-None-Match` → 304 from one small query, 503 when the catalog cannot be read — is
 * `lib/feed/changelogFeedRoute.ts`; rendering is the pure `lib/feed/changelog-feed` layer.
 */

import { renderChangelogRss } from '../../../../../../lib/feed/changelog-feed';
import { serveChangelogFeed } from '../../../../../../lib/feed/changelogFeedRoute';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ tenantSlug: string; projectSlug: string }> }
): Promise<Response> {
  const { tenantSlug, projectSlug } = await params;
  return serveChangelogFeed(request, tenantSlug, projectSlug, {
    extension: 'xml',
    contentType: 'application/rss+xml; charset=utf-8',
    render: renderChangelogRss,
  });
}
