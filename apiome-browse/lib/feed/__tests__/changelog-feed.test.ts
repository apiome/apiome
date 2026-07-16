/**
 * Tests for the project changelog feed builders — CTG-3.2 (#4476).
 *
 * Pins RSS 2.0 structure basics (declaration, balanced channel/item tags, self link), escaping
 * of hostile text, item ordering and title states (counts / initial publication / pending),
 * the JSON Feed 1.1 required keys and `_apiome` extension, ETag stability/quoting, and the
 * If-None-Match matcher.
 */

import { describe, expect, it } from 'vitest';
import type { ChangelogPayload, PublicVersionChangelogRow } from '../../changelog/types';
import {
  buildProjectFeedMeta,
  feedETag,
  feedUpdatedFromRows,
  ifNoneMatchMatches,
  renderChangelogJsonFeed,
  renderChangelogRss,
  type ChangelogFeedMeta,
} from '../changelog-feed';

const META: ChangelogFeedMeta = {
  projectName: 'Petstore',
  title: 'Petstore — API changelog',
  homeUrl: 'https://browse.example.com/tenant/acme/petstore',
  selfUrl: 'https://browse.example.com/tenant/acme/petstore/changelog.xml',
  description: 'Classified API changes for published versions of Petstore.',
  updated: new Date('2026-07-01T12:00:00Z'),
};

function payload(overrides: Partial<ChangelogPayload> = {}): ChangelogPayload {
  return {
    schemaVersion: 'ctg.changelog.v1',
    fromVersion: '1.0.0',
    toVersion: '1.1.0',
    counts: { breaking: 2, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 3 },
    maxSeverity: 'breaking',
    entries: [
      {
        severity: 'breaking',
        pathGroup: '/paths/~1pets',
        pointer: '/paths/~1pets/get',
        ruleId: 'operation.removed',
        changeKind: 'removed',
        summary: 'Operation removed.',
      },
      {
        severity: 'breaking',
        pathGroup: '/paths/~1pets',
        pointer: '/paths/~1pets/post/requestBody',
        ruleId: 'requestBody.required.added',
        changeKind: 'modified',
        summary: 'Request body became required.',
      },
      {
        severity: 'non-breaking',
        pathGroup: '/components/schemas/Pet',
        pointer: '/components/schemas/Pet/properties/tag',
        ruleId: 'property.added',
        changeKind: 'added',
        summary: 'Optional property added.',
      },
    ],
    ...overrides,
  };
}

function row(overrides: Partial<PublicVersionChangelogRow> = {}): PublicVersionChangelogRow {
  return {
    publishedRevisionId: '11111111-1111-1111-1111-111111111111',
    versionLabel: '1.1.0',
    publishedAt: '2026-06-30T08:00:00Z',
    baselineVersionLabel: '1.0.0',
    maxSeverity: 'breaking',
    status: 'ready',
    changelog: payload(),
    ...overrides,
  };
}

function initialRow(): PublicVersionChangelogRow {
  return row({
    publishedRevisionId: '22222222-2222-2222-2222-222222222222',
    versionLabel: '1.0.0',
    publishedAt: '2026-06-01T08:00:00Z',
    baselineVersionLabel: null,
    maxSeverity: null,
    status: 'initial',
    changelog: payload({
      fromVersion: null,
      toVersion: '1.0.0',
      counts: { breaking: 0, 'non-breaking': 0, 'docs-only': 0, unclassified: 0, total: 0 },
      maxSeverity: null,
      entries: [],
      initialPublication: true,
    }),
  });
}

function pendingRow(): PublicVersionChangelogRow {
  return row({
    publishedRevisionId: '33333333-3333-3333-3333-333333333333',
    versionLabel: '0.9.0',
    baselineVersionLabel: null,
    maxSeverity: null,
    status: null,
    changelog: null,
  });
}

function countTag(body: string, tag: string): number {
  return body.split(tag).length - 1;
}

describe('renderChangelogRss', () => {
  it('renders a structurally balanced RSS 2.0 document', () => {
    const body = renderChangelogRss(META, [row(), initialRow()]);
    expect(body.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(body).toContain('<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">');
    expect(countTag(body, '<channel>')).toBe(1);
    expect(countTag(body, '</channel>')).toBe(1);
    expect(countTag(body, '<item>')).toBe(2);
    expect(countTag(body, '</item>')).toBe(2);
    expect(body).toContain('<language>en</language>');
    expect(body).toContain(`<lastBuildDate>${META.updated.toUTCString()}</lastBuildDate>`);
    expect(body).toContain(
      '<atom:link rel="self" type="application/rss+xml" href="https://browse.example.com/tenant/acme/petstore/changelog.xml"/>'
    );
    expect(body.trimEnd().endsWith('</rss>')).toBe(true);
  });

  it('renders one item per row in input order with link, guid, and pubDate', () => {
    const body = renderChangelogRss(META, [row(), initialRow()]);
    const first = body.indexOf('Petstore 1.1.0');
    const second = body.indexOf('Petstore 1.0.0');
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(first);
    expect(body).toContain(
      '<link>https://browse.example.com/tenant/acme/petstore/1.1.0</link>'
    );
    expect(body).toContain(
      '<guid isPermaLink="false">11111111-1111-1111-1111-111111111111</guid>'
    );
    expect(body).toContain(`<pubDate>${new Date('2026-06-30T08:00:00Z').toUTCString()}</pubDate>`);
  });

  it('summarizes counts in the title and hides zero counts', () => {
    const body = renderChangelogRss(META, [row()]);
    expect(body).toContain('<title>Petstore 1.1.0 — 2 breaking, 1 non-breaking changes</title>');
    expect(body).not.toContain('0 docs-only');
  });

  it('uses the singular form for a single change', () => {
    const single = row({
      changelog: payload({
        counts: { breaking: 1, 'non-breaking': 0, 'docs-only': 0, unclassified: 0, total: 1 },
      }),
    });
    expect(renderChangelogRss(META, [single])).toContain('1 breaking change</title>');
  });

  it('titles initial-publication and pending rows', () => {
    const body = renderChangelogRss(META, [initialRow(), pendingRow()]);
    expect(body).toContain('<title>Petstore 1.0.0 — initial publication</title>');
    expect(body).toContain('<title>Petstore 0.9.0 — changes pending classification</title>');
  });

  it('lists grouped pointer — summary lines in the description', () => {
    const body = renderChangelogRss(META, [row()]);
    expect(body).toContain('Breaking:');
    expect(body).toContain('/paths/~1pets/get — Operation removed.');
    expect(body).toContain('Non-breaking:');
  });

  it('caps the description at 20 entries with an "…and N more" trailer', () => {
    const entries = Array.from({ length: 25 }, (_, i) => ({
      severity: 'breaking' as const,
      pathGroup: '/paths/~1pets',
      pointer: `/paths/~1pets/p${i}`,
      ruleId: 'r',
      changeKind: 'removed',
      summary: `change ${i}`,
    }));
    const big = row({
      changelog: payload({
        entries,
        counts: { breaking: 25, 'non-breaking': 0, 'docs-only': 0, unclassified: 0, total: 25 },
      }),
    });
    const body = renderChangelogRss(META, [big]);
    expect(body).toContain('change 19');
    expect(body).not.toContain('change 20');
    expect(body).toContain('…and 5 more');
  });

  it('escapes hostile text in titles and descriptions (no CDATA)', () => {
    const hostile = row({
      changelog: payload({
        entries: [
          {
            severity: 'breaking',
            pathGroup: '/paths/~1pets',
            pointer: '/paths/~1pets/get',
            ruleId: 'r',
            changeKind: 'removed',
            summary: 'Removed <b>"everything"</b> & more',
          },
        ],
      }),
    });
    const meta = { ...META, projectName: 'Pets & <Friends>', title: 'Pets & <Friends> feed' };
    const body = renderChangelogRss(meta, [hostile]);
    expect(body).not.toContain('<![CDATA[');
    expect(body).toContain('Pets &amp; &lt;Friends&gt;');
    expect(body).toContain('Removed &lt;b&gt;&quot;everything&quot;&lt;/b&gt; &amp; more');
    expect(body).not.toContain('<b>');
  });
});

describe('renderChangelogJsonFeed', () => {
  it('emits the JSON Feed 1.1 required keys', () => {
    const feed = renderChangelogJsonFeed(META, [row()]) as Record<string, unknown>;
    expect(feed.version).toBe('https://jsonfeed.org/version/1.1');
    expect(feed.title).toBe(META.title);
    expect(feed.home_page_url).toBe(META.homeUrl);
    expect(feed.feed_url).toBe(META.selfUrl);
    expect(feed.description).toBe(META.description);
    expect(Array.isArray(feed.items)).toBe(true);
  });

  it('maps each row to an item with id/url/title/date_published/content_text/_apiome', () => {
    const feed = renderChangelogJsonFeed(META, [row(), pendingRow()]) as {
      items: Record<string, unknown>[];
    };
    expect(feed.items).toHaveLength(2);
    const [ready, pending] = feed.items;
    expect(ready.id).toBe('11111111-1111-1111-1111-111111111111');
    expect(ready.url).toBe('https://browse.example.com/tenant/acme/petstore/1.1.0');
    expect(ready.title).toBe('Petstore 1.1.0 — 2 breaking, 1 non-breaking changes');
    expect(ready.date_published).toBe(new Date('2026-06-30T08:00:00Z').toISOString());
    expect(ready.content_text).toContain('/paths/~1pets/get — Operation removed.');
    expect(ready._apiome).toEqual({
      maxSeverity: 'breaking',
      status: 'ready',
      counts: { breaking: 2, 'non-breaking': 1, 'docs-only': 0, unclassified: 0, total: 3 },
      fromVersion: '1.0.0',
      toVersion: '1.1.0',
    });
    expect(pending._apiome).toEqual({
      maxSeverity: null,
      status: null,
      counts: null,
      fromVersion: null,
      toVersion: null,
    });
  });
});

describe('buildProjectFeedMeta', () => {
  it('builds absolute URLs from the request origin plus the base path', () => {
    const now = new Date('2026-07-01T00:00:00Z');
    const meta = buildProjectFeedMeta(
      'https://browse.example.com/tenant/acme/petstore/changelog.xml?x=1',
      '/browse',
      'Petstore',
      'acme',
      'petstore',
      'xml',
      now
    );
    expect(meta.homeUrl).toBe('https://browse.example.com/browse/tenant/acme/petstore');
    expect(meta.selfUrl).toBe(
      'https://browse.example.com/browse/tenant/acme/petstore/changelog.xml'
    );
    expect(meta.updated).toBe(now);
  });

  it('encodes slugs', () => {
    const meta = buildProjectFeedMeta(
      'https://x.example/tenant/a b/p',
      '',
      'P',
      'a b',
      'p/q',
      'json',
      new Date()
    );
    expect(meta.homeUrl).toBe('https://x.example/tenant/a%20b/p%2Fq');
  });
});

describe('feedUpdatedFromRows', () => {
  it('returns the newest publishedAt across rows', () => {
    const updated = feedUpdatedFromRows([
      row({ publishedAt: '2026-06-01T08:00:00Z' }),
      row({ publishedAt: '2026-06-30T08:00:00Z' }),
      row({ publishedAt: '2026-06-15T08:00:00Z' }),
    ]);
    expect(updated.toISOString()).toBe('2026-06-30T08:00:00.000Z');
  });

  it('ignores null and invalid dates, falling back to the epoch when none are valid', () => {
    expect(
      feedUpdatedFromRows([row({ publishedAt: null }), row({ publishedAt: 'not-a-date' })]).getTime(),
    ).toBe(0);
    expect(feedUpdatedFromRows([]).getTime()).toBe(0);
  });

  it('keeps the rendered feed byte-stable across renders (stable ETag → 304s work)', () => {
    const rows = [row(), initialRow()];
    const meta1 = { ...META, updated: feedUpdatedFromRows(rows) };
    const meta2 = { ...META, updated: feedUpdatedFromRows(rows) };
    expect(feedETag(renderChangelogRss(meta1, rows))).toBe(feedETag(renderChangelogRss(meta2, rows)));
  });
});

describe('feedETag', () => {
  it('is a quoted sha256 hex digest', () => {
    expect(feedETag('hello')).toMatch(/^"[0-9a-f]{64}"$/);
  });

  it('is stable for equal bodies and distinct for different ones', () => {
    expect(feedETag('a')).toBe(feedETag('a'));
    expect(feedETag('a')).not.toBe(feedETag('b'));
  });
});

describe('ifNoneMatchMatches', () => {
  const etag = feedETag('body');

  it('matches the exact ETag, list members, weak forms, and the wildcard', () => {
    expect(ifNoneMatchMatches(etag, etag)).toBe(true);
    expect(ifNoneMatchMatches(`"other", ${etag}`, etag)).toBe(true);
    expect(ifNoneMatchMatches(`W/${etag}`, etag)).toBe(true);
    expect(ifNoneMatchMatches('*', etag)).toBe(true);
  });

  it('rejects null and non-matching values', () => {
    expect(ifNoneMatchMatches(null, etag)).toBe(false);
    expect(ifNoneMatchMatches('"nope"', etag)).toBe(false);
  });
});
