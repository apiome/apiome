'use client';

/**
 * Public catalog analytics (V2-MCP-32.1 / MCAT-18.1) — the reduced, credential-free variant of the
 * private dashboard. It renders the published-public catalog roll-up in the browse idiom (stat pills
 * + simple horizontal bars, no chart kit): the endpoint count and average grade, then the category,
 * transport, and grade mixes. Everything is aggregated over `apiome.mcp_v_public_endpoints`, so only
 * published + public servers are ever reflected. Owns its empty (no public servers) state.
 */

import Link from 'next/link';
import { AppShell } from '../components/AppShell';
import type { McpPublicCatalogInsight } from '../../../lib/types';
import {
  mcpCatalogBucketTotal,
  mcpCatalogBucketViews,
  mcpPublicCatalogIsEmpty,
  mcpPublicGradeTone,
  type McpCatalogBucketView,
  type McpGradeTone,
} from '../../../lib/mcpCatalogInsight';

/** Bar fill classes per breakdown tone — token/utility classes only, light + dark. */
const BAR_TONE: Record<McpGradeTone | 'accent', string> = {
  good: 'bg-ok',
  ok: 'bg-honey',
  poor: 'bg-danger',
  accent: 'bg-accent',
};

/** One labelled bar: the label, a proportional fill, and the count + share. */
function BarRow({ row, tone }: { row: McpCatalogBucketView; tone: McpGradeTone | 'accent' }) {
  return (
    <li className="flex items-center gap-3 text-base">
      <span className="w-28 shrink-0 truncate text-fg-muted" title={row.label}>
        {row.label}
      </span>
      <span
        className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-subtle"
        aria-hidden="true"
      >
        <span
          className={`absolute inset-y-0 left-0 rounded-full ${BAR_TONE[tone]}`}
          style={{ width: `${Math.max(row.percent, row.count > 0 ? 3 : 0)}%` }}
        />
      </span>
      <span className="w-20 shrink-0 text-right tabular-nums text-fg-muted">
        {row.count}
        <span className="ml-1 text-fg-subtle">({row.percent}%)</span>
      </span>
    </li>
  );
}

/** One breakdown card: a titled list of bars, or a muted "no data" line. */
function BreakdownCard({
  title,
  rows,
  toneFor,
}: {
  title: string;
  rows: McpCatalogBucketView[];
  toneFor: (row: McpCatalogBucketView) => McpGradeTone | 'accent';
}) {
  return (
    <section className="rounded-lg border border-border bg-surface/60 p-5">
      <h2 className="mb-4 text-base font-semibold text-fg">{title}</h2>
      {rows.length === 0 ? (
        <p className="text-base text-fg-muted">No data yet.</p>
      ) : (
        <ul className="space-y-2.5">
          {rows.map((row) => (
            <BarRow key={row.label} row={row} tone={toneFor(row)} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function CatalogAnalyticsClient({ insight }: { insight: McpPublicCatalogInsight }) {
  const isEmpty = mcpPublicCatalogIsEmpty(insight);
  const categoryRows = mcpCatalogBucketViews(insight.category_distribution, insight.endpoint_count);
  const transportRows = mcpCatalogBucketViews(insight.transport_distribution, insight.endpoint_count);
  const gradeRows = mcpCatalogBucketViews(
    insight.grade_distribution,
    mcpCatalogBucketTotal(insight.grade_distribution),
  );

  return (
    <AppShell containerSize="wide">
      <header className="border-b border-border py-8">
        <p className="text-sm font-semibold uppercase tracking-wider text-accent-fg">
          MCP Catalog
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">
          Catalog analytics
        </h1>
        <p className="mt-2 max-w-2xl text-base text-fg-muted">
          How the published, public MCP servers in this directory break down by category, transport,
          and quality grade. Private and unpublished servers are never counted here.
        </p>
        <Link
          href="/mcp"
          className="mt-4 inline-flex items-center gap-1 text-base font-medium text-accent-fg hover:underline"
        >
          ← Back to the catalog
        </Link>
      </header>

      {isEmpty ? (
        <div className="my-10 rounded-lg border border-dashed border-border-strong bg-surface/50 p-10 text-center">
          <h2 className="text-xl font-semibold text-fg">
            No public MCP servers yet
          </h2>
          <p className="mx-auto mt-2 max-w-lg text-base text-fg-muted">
            Once servers are published publicly, catalog-wide analytics — category and transport mix
            and the grade distribution — appear here.
          </p>
        </div>
      ) : (
        <div className="my-8 space-y-6">
          {/* Headline tallies. */}
          <div className="flex flex-wrap gap-3">
            <div className="rounded-lg border border-border bg-surface/60 px-5 py-3">
              <div className="text-3xl font-bold tabular-nums text-fg">
                {insight.endpoint_count.toLocaleString()}
              </div>
              <div className="mt-0.5 text-xs font-medium uppercase tracking-wider text-fg-muted">
                Public servers
              </div>
            </div>
            <div className="rounded-lg border border-border bg-surface/60 px-5 py-3">
              <div className="text-3xl font-bold tabular-nums text-fg">
                {insight.average_score !== null ? insight.average_score.toFixed(1) : '—'}
              </div>
              <div className="mt-0.5 text-xs font-medium uppercase tracking-wider text-fg-muted">
                Average score
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            <BreakdownCard title="By category" rows={categoryRows} toneFor={() => 'accent'} />
            <BreakdownCard title="By transport" rows={transportRows} toneFor={() => 'accent'} />
            <BreakdownCard
              title="By grade"
              rows={gradeRows}
              toneFor={(row) => mcpPublicGradeTone(row.label)}
            />
          </div>
        </div>
      )}
    </AppShell>
  );
}
