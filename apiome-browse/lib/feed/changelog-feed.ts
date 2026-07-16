/**
 * Project changelog feed rendering — pure RSS 2.0 / JSON Feed 1.1 builders (CTG-3.2, #4476).
 *
 * The rendering layer behind `/tenant/{t}/{p}/changelog.xml` and `.json`, mirroring the REST
 * side's `mcp_change_feed.py` design rules: framework-free and deterministic (every timestamp is
 * supplied by the caller), all interpolated text XML-escaped so a hostile summary or project name
 * can never break the document, and content-addressed ETags (`feedETag`) so a polling reader gets
 * a clean 304 until the changelog actually moves. Rows come from
 * `getPublicChangelogsForProject`, which already applies the public gate — this layer only
 * renders what it is handed and never sees the private `error` column.
 */

import { createHash } from 'node:crypto';
import type { PublicVersionChangelogRow, Severity } from '../changelog/types';
import { groupChangelogEntries, severityLabel } from '../changelog/group';

/** Feed-level metadata shared by both serializations. All URLs are absolute. */
export interface ChangelogFeedMeta {
  /** The project's display name (used in the per-item titles). */
  projectName: string;
  /** Feed title (e.g. `"Petstore — API changelog"`). */
  title: string;
  /** The public project page URL (channel link / `home_page_url`; item links hang off it). */
  homeUrl: string;
  /** The feed's own URL (the `atom:link rel="self"` / `feed_url`). */
  selfUrl: string;
  /** One-line feed description. */
  description: string;
  /** Fallback timestamp (typically render time) for the feed and undated items. */
  updated: Date;
}

/**
 * Feed metadata for a project changelog feed, with absolute URLs assembled from the request's
 * origin plus the deployment base path. Pure — the caller supplies the clock (`now`).
 */
export function buildProjectFeedMeta(
  requestUrl: string,
  basePath: string,
  projectName: string,
  tenantSlug: string,
  projectSlug: string,
  extension: 'xml' | 'json',
  now: Date
): ChangelogFeedMeta {
  const origin = new URL(requestUrl).origin;
  const homeUrl = `${origin}${basePath}/tenant/${encodeURIComponent(tenantSlug)}/${encodeURIComponent(projectSlug)}`;
  return {
    projectName,
    title: `${projectName} — API changelog`,
    homeUrl,
    selfUrl: `${homeUrl}/changelog.${extension}`,
    description: `Classified API changes for published versions of ${projectName}.`,
    updated: now,
  };
}

/**
 * The feed's `updated` timestamp derived from its rows: the newest valid `publishedAt`, or the
 * Unix epoch when no row carries one. Data-derived (never the render clock) so the rendered body
 * — and therefore `feedETag` — only changes when the changelog actually does, keeping
 * `If-None-Match` → 304 effective for polling readers.
 */
export function feedUpdatedFromRows(rows: readonly PublicVersionChangelogRow[]): Date {
  let max = 0;
  for (const row of rows) {
    if (row.publishedAt == null) continue;
    const t = new Date(row.publishedAt).getTime();
    if (!Number.isNaN(t) && t > max) max = t;
  }
  return new Date(max);
}

/** Escape the five XML-significant characters in interpolated text. */
function escapeXml(raw: string): string {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/** Coerce a row's `publishedAt` (Date, ISO string, or null) to a Date, else the fallback. */
function itemDate(row: PublicVersionChangelogRow, fallback: Date): Date {
  if (row.publishedAt != null) {
    const d = new Date(row.publishedAt);
    if (!Number.isNaN(d.getTime())) return d;
  }
  return fallback;
}

/** The version label an item's title/link should show (`toVersion` from the payload, else the row). */
function itemVersionLabel(row: PublicVersionChangelogRow): string {
  return row.changelog?.toVersion || row.versionLabel;
}

/** The public version page URL for a row. */
function itemUrl(meta: ChangelogFeedMeta, row: PublicVersionChangelogRow): string {
  return `${meta.homeUrl}/${encodeURIComponent(row.versionLabel)}`;
}

/**
 * The item title suffix summarizing the row: nonzero severity counts (`2 breaking,
 * 1 non-breaking changes`), or the initial-publication / pending-classification states.
 */
function itemTitleSuffix(row: PublicVersionChangelogRow): string {
  if (row.status === 'initial' || row.changelog?.initialPublication) {
    return 'initial publication';
  }
  const counts = row.status === 'ready' ? row.changelog?.counts : undefined;
  if (!counts) return 'changes pending classification';

  const severities: Severity[] = ['breaking', 'non-breaking', 'docs-only'];
  const parts: string[] = [];
  let shown = 0;
  for (const severity of severities) {
    const n = counts[severity] ?? 0;
    if (n > 0) {
      parts.push(`${n} ${severity}`);
      shown += n;
    }
  }
  if (parts.length === 0) return 'no changes detected';
  return `${parts.join(', ')} change${shown === 1 ? '' : 's'}`;
}

/** One item's title: `{projectName} {toVersion} — {suffix}`. */
function itemTitle(meta: ChangelogFeedMeta, row: PublicVersionChangelogRow): string {
  return `${meta.projectName} ${itemVersionLabel(row)} — ${itemTitleSuffix(row)}`;
}

/** Maximum changelog entries an item description enumerates before "…and N more". */
const DESCRIPTION_ENTRY_CAP = 20;

/**
 * A plain-text summary of one row's changes: severity headings with `pointer — summary` lines,
 * capped at {@link DESCRIPTION_ENTRY_CAP} entries. Shared by the RSS description (escaped by the
 * caller) and the JSON Feed `content_text`.
 */
function itemSummaryText(row: PublicVersionChangelogRow): string {
  if (row.status === 'initial' || row.changelog?.initialPublication) {
    return 'Initial publication — no prior baseline to compare against.';
  }
  if (row.status !== 'ready' || !row.changelog) {
    return 'Changes are pending classification.';
  }
  const entries = row.changelog.entries ?? [];
  if (entries.length === 0) {
    return 'No changes detected.';
  }

  const lines: string[] = [];
  let emitted = 0;
  let truncated = false;
  for (const section of groupChangelogEntries(entries)) {
    if (truncated) break;
    lines.push(`${severityLabel(section.severity)}:`);
    for (const group of section.groups) {
      for (const entry of group.entries) {
        if (emitted >= DESCRIPTION_ENTRY_CAP) {
          truncated = true;
          break;
        }
        lines.push(`${entry.pointer} — ${entry.summary}`);
        emitted += 1;
      }
      if (truncated) break;
    }
  }
  if (truncated) {
    lines.push(`…and ${entries.length - emitted} more`);
  }
  return lines.join('\n');
}

/**
 * Render a project's changelog rows as an RSS 2.0 document (newest first — the caller supplies
 * rows already ordered). Every interpolated value is escaped; no CDATA sections.
 */
export function renderChangelogRss(
  meta: ChangelogFeedMeta,
  items: PublicVersionChangelogRow[]
): string {
  const parts: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
    '<channel>',
    `<title>${escapeXml(meta.title)}</title>`,
    `<link>${escapeXml(meta.homeUrl)}</link>`,
    `<description>${escapeXml(meta.description)}</description>`,
    '<language>en</language>',
    `<lastBuildDate>${escapeXml(meta.updated.toUTCString())}</lastBuildDate>`,
    `<atom:link rel="self" type="application/rss+xml" href="${escapeXml(meta.selfUrl)}"/>`,
  ];

  for (const row of items) {
    parts.push(
      '<item>',
      `<title>${escapeXml(itemTitle(meta, row))}</title>`,
      `<link>${escapeXml(itemUrl(meta, row))}</link>`,
      `<guid isPermaLink="false">${escapeXml(row.publishedRevisionId)}</guid>`,
      `<pubDate>${escapeXml(itemDate(row, meta.updated).toUTCString())}</pubDate>`,
      `<description>${escapeXml(itemSummaryText(row))}</description>`,
      '</item>'
    );
  }

  parts.push('</channel>', '</rss>');
  return parts.join('\n');
}

/** Render a project's changelog rows as a JSON Feed 1.1 object. */
export function renderChangelogJsonFeed(
  meta: ChangelogFeedMeta,
  items: PublicVersionChangelogRow[]
): object {
  return {
    version: 'https://jsonfeed.org/version/1.1',
    title: meta.title,
    home_page_url: meta.homeUrl,
    feed_url: meta.selfUrl,
    description: meta.description,
    items: items.map((row) => ({
      id: row.publishedRevisionId,
      url: itemUrl(meta, row),
      title: itemTitle(meta, row),
      date_published: itemDate(row, meta.updated).toISOString(),
      content_text: itemSummaryText(row),
      _apiome: {
        maxSeverity: row.maxSeverity,
        status: row.status,
        counts: row.changelog?.counts ?? null,
        fromVersion: row.changelog?.fromVersion ?? null,
        toVersion: row.changelog?.toVersion ?? null,
      },
    })),
  };
}

/**
 * A strong, content-addressed ETag (quoted sha256 hex) for a rendered feed body — changes exactly
 * when the feed does, so `If-None-Match` polling short-circuits to 304 until then.
 */
export function feedETag(body: string): string {
  return `"${createHash('sha256').update(body, 'utf8').digest('hex')}"`;
}

/**
 * Whether a request's `If-None-Match` header already carries this feed's ETag (tolerating a
 * comma-separated list, `W/` weak prefixes, and the `*` wildcard).
 */
export function ifNoneMatchMatches(header: string | null, etag: string): boolean {
  if (!header) return false;
  for (const candidate of header.split(',')) {
    let token = candidate.trim();
    if (token.startsWith('W/')) token = token.slice(2).trim();
    if (token === etag || token === '*') return true;
  }
  return false;
}
