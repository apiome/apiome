/**
 * `GET /tenant/{tenantSlug}/{projectSlug}/changelog.md` — the project changelog page as Markdown
 * (PCX-2.1, #5896).
 *
 * The text is rendered by REST (`GET /v1/browse/tenants/{t}/projects/{p}/changelog.md`, built on
 * `render_changelog_markdown`) so there is exactly one Markdown renderer; this route forwards the
 * page's filters (`severity`, `pathGroup`, `since`) and `If-None-Match`, and relays the body,
 * ETag and cache headers. Anonymous and cacheable.
 */

import { serverRestBase } from '../../../../../../lib/portal/api';
import { changelogMarkdownUpstreamUrl } from '../../../../../../lib/changelog/markdownRoute';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: Request,
  { params }: { params: Promise<{ tenantSlug: string; projectSlug: string }> }
): Promise<Response> {
  const { tenantSlug, projectSlug } = await params;
  const upstream = changelogMarkdownUpstreamUrl(
    serverRestBase(process.env),
    tenantSlug,
    projectSlug,
    new URL(request.url).searchParams
  );

  const headers: Record<string, string> = { Accept: 'text/markdown' };
  const inm = request.headers.get('if-none-match');
  if (inm) headers['If-None-Match'] = inm;

  let res: Response;
  try {
    res = await fetch(upstream, { headers, cache: 'no-store' });
  } catch {
    return new Response('Changelog unavailable', { status: 502 });
  }

  const out = new Headers();
  for (const name of ['content-type', 'etag', 'cache-control']) {
    const value = res.headers.get(name);
    if (value) out.set(name, value);
  }
  if (res.status === 304) return new Response(null, { status: 304, headers: out });
  if (res.status === 404) return new Response('Not found', { status: 404 });
  if (!res.ok) return new Response('Changelog unavailable', { status: 502 });
  return new Response(await res.text(), { status: 200, headers: out });
}
