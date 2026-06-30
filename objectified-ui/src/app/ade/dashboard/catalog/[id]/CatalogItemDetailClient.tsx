'use client';

/**
 * CatalogItemDetailClient (MFI-23.9, #4018).
 *
 * The catalog item *detail* view — "what was imported and where it came from". It mirrors the other
 * dashboard detail screens (a back link, an avatar/title header, then panels) and reuses the catalog
 * pills (MFI-23.5) and the shared `ProjectQualityHistoryDialog` (so the quality/lint orbs open the
 * very same dialogs the Projects and Catalog screens use — a catalog item's id *is* a project id).
 *
 * It renders four things off the `/api/catalog/{id}` detail payload (MFI-23.2 envelope + the 23.9
 * enrichments):
 *   1. **Source material** — file name / URL / discovery, viewable + downloadable via the
 *      `/api/catalog/{id}/source` proxy (streams captured content, or redirects to the source URL).
 *   2. **Provenance** — format/protocol, tool versions, import-job reference, timestamps + creator.
 *   3. **Normalized summary** — services / operations / types / channels counts.
 *   4. **Quality & lint** — the score/grade orbs, linking into the shared history dialog.
 *
 * There is intentionally **no Publish/Edit** here: catalog items are the non-publishable slice of
 * projects (MFI-23.1), minted by the import routing (MFI-23.7), and read-only on this screen.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileSearch,
  GitBranch,
  Wrench,
} from 'lucide-react';
import { cn } from '@lib/utils';
import {
  getNumericScoreTier,
  letterGradeFromOverallPercent,
  type NumericScoreTierStyle,
} from '@/app/utils/numeric-score-tier';
import { getProjectQualityHistory } from '@/app/utils/project-quality-score-history';
import { ProjectQualityHistoryDialog } from '@/app/components/ade/dashboard/ProjectQualityHistoryDialog';
import { CatalogLintReportDialog } from '@/app/components/ade/dashboard/catalog/CatalogLintReportDialog';
import { FormatPill } from '@/app/components/ui/catalog/FormatPill';
import { ProtocolPill } from '@/app/components/ui/catalog/ProtocolPill';
import { SourceBadge } from '@/app/components/ui/catalog/SourceBadge';
import { resolveCatalogSource } from '@/app/utils/catalog-format-registry';
import {
  catalogCardGradientClass,
  catalogCardInitials,
  formatShortCatalogId,
} from '@/app/utils/catalog-card-presentation';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  dashboardMainClass,
  dashboardContentStackClass,
  dashboardPanelClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';

/** The normalized-content counts the import recorded for the item (each null until captured). */
interface CatalogNormalizedSummary {
  services: number | null;
  operations: number | null;
  types: number | null;
  channels: number | null;
}

/** Where the item was imported from, plus whether the raw source is retrievable. */
interface CatalogSourceDescriptor {
  kind: 'file' | 'url' | 'paste' | 'discovery' | null;
  label: string | null;
  uri: string | null;
  hasContent: boolean;
  downloadable: boolean;
}

/** The detail payload (MFI-23.2 envelope + MFI-23.9 `summary`/`source`). */
interface CatalogItemDetail {
  id: string;
  name: string;
  slug?: string | null;
  description?: string | null;
  enabled: boolean;
  deleted_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  creator_name?: string | null;
  creator_email?: string | null;
  metadata?: Record<string, unknown> | null;
  qualityScore?: number | null;
  qualityGrade?: string | null;
  publishable?: boolean;
  sourceFormat?: string | null;
  protocol?: string | null;
  formatMetadata?: Record<string, unknown> | null;
  toolVersions?: Record<string, unknown> | null;
  summary?: CatalogNormalizedSummary;
  source?: CatalogSourceDescriptor;
}

const CATALOG_LIST_HREF = '/ade/dashboard/catalog';

/** The orb border colour for a quality/lint band (mirrors CatalogItemCard). */
function scoreOrbBorderClass(band: NumericScoreTierStyle['band'] | null): string {
  if (!band) return 'border-gray-300 dark:border-gray-600';
  if (band === 'excellent') return 'border-emerald-500';
  if (band === 'good') return 'border-indigo-500';
  if (band === 'fair') return 'border-amber-500';
  return 'border-rose-500';
}

/** Format an ISO timestamp for display, tolerating null/invalid input. */
function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

/** The candidate keys an import-job reference may travel under in the provenance bag. */
const IMPORT_JOB_KEYS = ['importJobId', 'import_job_id', 'jobId', 'job_id', 'importJob', 'import_job'];

/** Read the first present, non-empty string value among `keys` from a loose bag. */
function firstString(bag: Record<string, unknown> | null | undefined, keys: string[]): string | null {
  if (!bag) return null;
  for (const k of keys) {
    const v = bag[k];
    if (typeof v === 'string' && v.trim()) return v.trim();
    if (typeof v === 'number') return String(v);
  }
  return null;
}

/** A labelled metric tile in the normalized-summary grid. */
function SummaryCard({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="flex flex-col rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800">
      <span className="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
        {label}
      </span>
      <span className="mt-1 font-mono text-2xl font-semibold tabular-nums text-gray-900 dark:text-white">
        {typeof value === 'number' ? value : '—'}
      </span>
    </div>
  );
}

/** A labelled key/value row used inside the provenance panel. */
function ProvenanceRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:gap-4">
      <span className="w-40 shrink-0 text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
        {label}
      </span>
      <span className="min-w-0 text-sm text-gray-800 dark:text-gray-200">{children}</span>
    </div>
  );
}

export function CatalogItemDetailClient({ itemId }: { itemId: string }) {
  const router = useRouter();
  const [item, setItem] = useState<CatalogItemDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [qualityOpen, setQualityOpen] = useState(false);
  // Server-backed lint report (same report Projects use, MFI-23.10).
  const [lintOpen, setLintOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/catalog/${encodeURIComponent(itemId)}`);
      const data = await res.json();
      if (!res.ok || !data?.success || !data.item) {
        setError(data?.error || 'Catalog item not found.');
        setItem(null);
      } else {
        setItem(data.item as CatalogItemDetail);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load catalog item.');
      setItem(null);
    } finally {
      setLoading(false);
    }
  }, [itemId]);

  useEffect(() => {
    void load();
  }, [load]);

  // The orbs reuse the project quality-history machinery (a catalog item's id is a project id),
  // falling back to the server-captured score/grade when there is no browser-local history.
  const qualityHistory = useMemo(
    () => (item ? getProjectQualityHistory(item.id) : []),
    [item],
  );
  const qualityValue = useMemo(() => {
    const latest = qualityHistory.length > 0 ? qualityHistory[qualityHistory.length - 1] : null;
    if (latest != null) return latest.overall;
    return typeof item?.qualityScore === 'number' ? item.qualityScore : null;
  }, [qualityHistory, item]);
  const scoreTier = qualityValue != null ? getNumericScoreTier(qualityValue) : null;
  const lintLetter =
    qualityValue != null ? letterGradeFromOverallPercent(qualityValue) : item?.qualityGrade ?? null;


  if (loading) {
    return (
      <main className={dashboardMainClass}>
        <LoadingState message="Loading catalog item…" />
      </main>
    );
  }

  if (error || !item) {
    return (
      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          <Link
            href={CATALOG_LIST_HREF}
            className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline dark:text-indigo-400"
          >
            <ArrowLeft className="h-4 w-4" /> Catalog
          </Link>
          <div
            data-testid="catalog-detail-error"
            className={`${dashboardPanelClass} p-10 text-center text-sm text-gray-600 dark:text-gray-400`}
          >
            {error || 'Catalog item not found.'}
          </div>
        </div>
      </main>
    );
  }

  const isDeleted = Boolean(item.deleted_at);
  const source = item.source ?? null;
  const resolvedSource = resolveCatalogSource(item.formatMetadata, item.metadata);
  const summary = item.summary ?? { services: null, operations: null, types: null, channels: null };
  const hasAnyCount =
    typeof summary.services === 'number' ||
    typeof summary.operations === 'number' ||
    typeof summary.types === 'number' ||
    typeof summary.channels === 'number';
  const toolVersionEntries = Object.entries(item.toolVersions ?? {}).filter(
    ([, v]) => v != null && String(v).trim() !== '',
  );
  const importJobRef = firstString(item.formatMetadata, IMPORT_JOB_KEYS);
  const sourceHref = `/api/catalog/${encodeURIComponent(item.id)}/source`;

  return (
    <main className={dashboardMainClass}>
      <div className={dashboardContentStackClass}>
        <Link
          href={CATALOG_LIST_HREF}
          className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline dark:text-indigo-400"
        >
          <ArrowLeft className="h-4 w-4" /> Catalog
        </Link>

        {/* Header */}
        <section className={`${dashboardPanelClass} p-6`} data-testid="catalog-detail-header">
          <div className="flex flex-wrap items-start gap-4">
            <span
              className={cn(
                'inline-flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br font-mono text-lg font-bold text-white',
                catalogCardGradientClass(item.id),
              )}
              aria-hidden
            >
              {catalogCardInitials(item.name)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-xl font-bold text-gray-900 dark:text-white" title={item.name}>
                  {item.name}
                </h1>
                {isDeleted ? (
                  <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                    Deleted
                  </span>
                ) : !item.enabled ? (
                  <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                    Disabled
                  </span>
                ) : (
                  <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                    Active
                  </span>
                )}
              </div>
              <p className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-400">
                {formatShortCatalogId(item.id)}
                {item.slug ? ` · ${item.slug}` : ''}
              </p>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                {item.description?.trim() || 'No description.'}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <FormatPill format={item.sourceFormat} />
                <ProtocolPill protocol={item.protocol} />
                {resolvedSource ? <SourceBadge source={resolvedSource} /> : null}
              </div>
            </div>

            {/* Quality + lint orbs (open the shared dialog). */}
            <div className="flex shrink-0 items-start gap-4">
              <div className="text-center">
                <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Quality
                </p>
                {qualityValue != null ? (
                  <button
                    type="button"
                    data-testid="catalog-detail-quality-orb"
                    onClick={() => setQualityOpen(true)}
                    className={cn(
                      'mt-1 inline-flex h-11 w-11 items-center justify-center rounded-full border-2 font-mono text-xs font-semibold tabular-nums hover:bg-indigo-50/50 dark:hover:bg-indigo-950/30',
                      scoreOrbBorderClass(scoreTier!.band),
                      scoreTier!.textClass,
                    )}
                    title="Open quality score history"
                  >
                    {qualityValue}
                  </button>
                ) : (
                  <span className="mt-1 inline-flex h-11 w-11 items-center justify-center rounded-full border-2 border-gray-300 font-mono text-xs text-gray-400 dark:border-gray-600">
                    —
                  </span>
                )}
              </div>
              <div className="text-center">
                <p className="text-[10px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                  Lint
                </p>
                {lintLetter ? (
                  <button
                    type="button"
                    data-testid="catalog-detail-lint-orb"
                    onClick={() => setLintOpen(true)}
                    className={cn(
                      'mt-1 inline-flex h-11 w-11 items-center justify-center rounded-full border-2 font-mono text-xs font-semibold tabular-nums hover:bg-indigo-50/50 dark:hover:bg-indigo-950/30',
                      scoreOrbBorderClass(scoreTier?.band ?? null),
                      scoreTier?.textClass ?? 'text-gray-500 dark:text-gray-400',
                    )}
                    title="Open lint report"
                  >
                    {lintLetter}
                  </button>
                ) : (
                  <span className="mt-1 inline-flex h-11 w-11 items-center justify-center rounded-full border-2 border-gray-300 font-mono text-xs text-gray-400 dark:border-gray-600">
                    —
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => router.push(`/ade/dashboard/versions?projectId=${encodeURIComponent(item.id)}`)}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              <GitBranch className="h-4 w-4 text-indigo-500" /> View versions
            </button>
            <button
              type="button"
              onClick={() => setLintOpen(true)}
              className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              <FileSearch className="h-4 w-4 text-indigo-500" /> Lint report
            </button>
          </div>
        </section>

        {/* Source material */}
        <section className={`${dashboardPanelClass} p-6`} data-testid="catalog-detail-source">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
            Source material
          </h2>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            {resolvedSource ? (
              <SourceBadge source={resolvedSource} />
            ) : (
              <span className="text-sm text-gray-500 dark:text-gray-400">
                Original source provenance was not recorded for this item.
              </span>
            )}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {source?.downloadable ? (
              <>
                <a
                  href={sourceHref}
                  data-testid="catalog-detail-download"
                  className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-700"
                  {...(source.hasContent ? { download: '' } : { target: '_blank', rel: 'noopener noreferrer' })}
                >
                  <Download className="h-4 w-4" /> {source.hasContent ? 'Download raw source' : 'View source'}
                </a>
                {source.uri ? (
                  <a
                    href={source.uri}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                  >
                    <ExternalLink className="h-4 w-4 text-indigo-500" /> Open source URL
                  </a>
                ) : null}
              </>
            ) : (
              <span
                data-testid="catalog-detail-no-source"
                className="text-sm text-gray-500 dark:text-gray-400"
              >
                The raw source was not captured at import, so it cannot be downloaded here.
              </span>
            )}
          </div>
        </section>

        {/* Normalized summary */}
        <section className={`${dashboardPanelClass} p-6`} data-testid="catalog-detail-summary">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
            Normalized summary
          </h2>
          {hasAnyCount ? (
            <div className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <SummaryCard label="Services" value={summary.services} />
              <SummaryCard label="Operations" value={summary.operations} />
              <SummaryCard label="Types" value={summary.types} />
              <SummaryCard label="Channels" value={summary.channels} />
            </div>
          ) : (
            <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
              The normalized-content summary has not been captured for this item yet.
            </p>
          )}
        </section>

        {/* Provenance */}
        <section className={`${dashboardPanelClass} p-6`} data-testid="catalog-detail-provenance">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
            Provenance
          </h2>
          <div className="mt-2 divide-y divide-gray-100 dark:divide-gray-700/60">
            <ProvenanceRow label="Format">
              {item.sourceFormat ? <FormatPill format={item.sourceFormat} /> : <span className="text-gray-400">—</span>}
            </ProvenanceRow>
            <ProvenanceRow label="Protocol">
              {item.protocol ? <ProtocolPill protocol={item.protocol} /> : <span className="text-gray-400">—</span>}
            </ProvenanceRow>
            <ProvenanceRow label="Tool versions">
              {toolVersionEntries.length > 0 ? (
                <span className="flex flex-wrap gap-1.5">
                  {toolVersionEntries.map(([tool, version]) => (
                    <span
                      key={tool}
                      className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700 dark:bg-gray-700/60 dark:text-gray-300"
                    >
                      <Wrench className="h-3 w-3" aria-hidden /> {tool} {String(version)}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="text-gray-400">Not recorded</span>
              )}
            </ProvenanceRow>
            <ProvenanceRow label="Import job">
              {importJobRef ? (
                <span className="font-mono text-xs">{importJobRef}</span>
              ) : (
                <span className="text-gray-400">Not recorded</span>
              )}
            </ProvenanceRow>
            <ProvenanceRow label="Created">{formatTimestamp(item.created_at)}</ProvenanceRow>
            <ProvenanceRow label="Updated">{formatTimestamp(item.updated_at)}</ProvenanceRow>
            <ProvenanceRow label="Created by">
              {item.creator_name || item.creator_email || 'Unknown'}
            </ProvenanceRow>
          </div>
        </section>
      </div>

      <ProjectQualityHistoryDialog
        key={qualityOpen ? `${item.id}:quality` : 'catalog-detail-dialog-closed'}
        open={qualityOpen}
        onOpenChange={setQualityOpen}
        projectName={item.name}
        projectId={item.id}
        history={qualityHistory}
        initialSection="quality"
      />

      <CatalogLintReportDialog
        key={lintOpen ? `${item.id}:lint` : 'catalog-detail-lint-closed'}
        itemId={lintOpen ? item.id : null}
        itemName={item.name}
        open={lintOpen}
        onOpenChange={setLintOpen}
      />
    </main>
  );
}
