'use client';

import { useMemo, useState } from 'react';
import {
  BADGE_METRICS,
  BADGE_METRIC_LABELS,
  BADGE_THEMES,
  type BadgeMetric,
  type BadgeSnippetFormat,
  type BadgeTheme,
  badgeAltText,
  badgeImageUrl,
  badgeLinkUrl,
  badgeSnippet,
} from '../../../../../lib/mcp/badge';

const FORMAT_ORDER: BadgeSnippetFormat[] = ['markdown', 'html', 'url'];
const FORMAT_LABELS: Record<BadgeSnippetFormat, string> = {
  markdown: 'Markdown',
  html: 'HTML',
  url: 'URL',
};

/**
 * Status-badge snippet (MCAT-19.3): live preview of the endpoint's public SVG badge plus a
 * ready-to-copy Markdown / HTML / URL snippet an author drops into a README. Metric (grade / health
 * / version) and light/dark label variant are selectable; the snippet and preview update together.
 *
 * Only rendered on a public (published) endpoint's detail page, so the badge it points at always
 * resolves. The badge URL targets the anonymous `/mcp/badge/...` REST surface; the link wraps it to
 * the endpoint's own detail page.
 */
export function McpBadgeSnippet({
  restApiBaseUrl,
  tenantSlug,
  endpointSlug,
  endpointName,
}: {
  restApiBaseUrl: string;
  tenantSlug: string;
  endpointSlug: string;
  endpointName: string;
}) {
  const [metric, setMetric] = useState<BadgeMetric>('grade');
  const [theme, setTheme] = useState<BadgeTheme>('light');
  const [format, setFormat] = useState<BadgeSnippetFormat>('markdown');
  const [copied, setCopied] = useState(false);

  // The badge link points at this app's own detail page; the origin is only known in the browser, so
  // it is empty during SSR and resolves on the client. The rendered snippet therefore differs between
  // server and client (`suppressHydrationWarning` on the <code> below acknowledges that).
  const appOrigin = useMemo(() => (typeof window === 'undefined' ? '' : window.location.origin), []);

  const imageUrl = useMemo(
    () => badgeImageUrl(restApiBaseUrl, tenantSlug, endpointSlug, metric, theme),
    [restApiBaseUrl, tenantSlug, endpointSlug, metric, theme]
  );
  const linkUrl = useMemo(
    () => badgeLinkUrl(appOrigin, tenantSlug, endpointSlug),
    [appOrigin, tenantSlug, endpointSlug]
  );
  const snippet = useMemo(
    () => badgeSnippet(format, imageUrl, linkUrl, badgeAltText(endpointName, metric)),
    [format, imageUrl, linkUrl, endpointName, metric]
  );

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className="mt-8 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">Status badge</h2>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            Embed this endpoint&apos;s catalog assessment in a README.
          </p>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element -- external SVG badge, no Next loader */}
        <img
          src={imageUrl}
          alt={badgeAltText(endpointName, metric)}
          height={20}
          className="h-5"
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-4">
        <div>
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Metric
          </span>
          <div className="inline-flex gap-1" role="group" aria-label="Badge metric">
            {BADGE_METRICS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMetric(m)}
                aria-pressed={metric === m}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  metric === m
                    ? 'bg-[var(--brand)] text-white'
                    : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
                }`}
              >
                {BADGE_METRIC_LABELS[m]}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
            Theme
          </span>
          <div className="inline-flex gap-1" role="group" aria-label="Badge theme">
            {BADGE_THEMES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                aria-pressed={theme === t}
                className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors ${
                  theme === t
                    ? 'bg-[var(--brand)] text-white'
                    : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {FORMAT_ORDER.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFormat(f)}
            className={`-mb-px border-b-2 px-3 py-1.5 text-xs font-medium transition-colors ${
              format === f
                ? 'border-[var(--brand)] text-[var(--brand)]'
                : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
            }`}
          >
            {FORMAT_LABELS[f]}
          </button>
        ))}
      </div>

      <div className="mt-3 flex items-stretch gap-2">
        <code
          suppressHydrationWarning
          className="min-w-0 flex-1 overflow-x-auto whitespace-pre rounded-lg bg-zinc-50 p-3 font-mono text-xs text-zinc-700 ring-1 ring-inset ring-zinc-200 dark:bg-zinc-950 dark:text-zinc-300 dark:ring-zinc-800"
        >
          {snippet}
        </code>
        <button
          type="button"
          onClick={handleCopy}
          className="shrink-0 self-start rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </section>
  );
}
