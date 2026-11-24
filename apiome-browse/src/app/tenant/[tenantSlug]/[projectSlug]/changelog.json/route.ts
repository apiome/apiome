/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/changelog.json` — the project's public changelog as a
 * JSON Feed 1.1 document (CTG-3.2, #4476). The JSON sibling of `changelog.xml/route.ts`; same
 * public gate, ETag/304 handling and cache policy (`lib/feed/changelogFeedRoute.ts`).
 */

import { renderChangelogJsonFeed } from '../../../../../../lib/feed/changelog-feed';
import { serveChangelogFeed } from '../../../../../../lib/feed/changelogFeedRoute';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ tenantSlug: string; projectSlug: string }> }
): Promise<Response> {
  const { tenantSlug, projectSlug } = await params;
  return serveChangelogFeed(request, tenantSlug, projectSlug, {
    extension: 'json',
    contentType: 'application/feed+json; charset=utf-8',
    render: (meta, rows) => JSON.stringify(renderChangelogJsonFeed(meta, rows)),
  });
}
