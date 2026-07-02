'use client';

/**
 * CatalogLintPanel (MFI-25.5, #4090) — the inline Lint & Score pane.
 *
 * The mockup renders lint *inline* in the detail's Lint & Score tab (mockup lint pane,
 * `index.html:496-506`, `1529-1540`), not just behind the `CatalogLintReportDialog`. This component
 * fetches the same authoritative server report (`GET /api/catalog/{id}/lint`) the dialog uses and
 * renders it as:
 *   - a **grade gauge** — an SVG progress ring coloured by the score band, with the server letter
 *     grade + `score/100` in the centre;
 *   - **category bars** — real per-category 0–100 scores when MFI-25.6 ships them (`report.categories`),
 *     otherwise a graceful **severity breakdown** derived from the findings (which categories carry
 *     the most severe findings), so the bars are always meaningful without inventing a score;
 *   - a **findings list** — severity chip + rule + message + a MUST/SHOULD conformance chip.
 *
 * The fetch is **lazy** (only once the Lint tab is active) and **one-shot** (re-activating never
 * refetches), mirroring {@link CatalogSourceViewer}. The full dialog stays reachable from the header
 * lint orb and the "Open full report" affordance here, so the itemized history view is preserved.
 *
 * The score/grade are the server's authoritative values — nothing here recomputes them; the tier
 * helper is used only to pick band colours.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  Clock,
  FileSearch,
  Fingerprint,
  History,
  RefreshCw,
} from 'lucide-react';
import { cn } from '@lib/utils';
import { dashboardPanelClass } from '@/app/components/ade/dashboard/dashboardScreenClasses';
import {
  fetchCatalogLintReport,
  gradeChipClass,
  sortLintFindings,
  type VersionLintFinding,
  type VersionLintReport,
} from '@/app/utils/version-lint-report';
import { getNumericScoreTier } from '@/app/utils/numeric-score-tier';
import {
  catalogLintGroupByTier,
  catalogLintProvenance,
  deriveCategorySeverityBreakdown,
  gaugeDashOffset,
  humanizeCategory,
  resolveCatalogFindingEntity,
  resolveCategoryScores,
  type CatalogLintTierMeta,
  type CategorySeverityBreakdown,
} from '@/app/utils/catalog-lint-panel';

/** SVG progress-ring geometry (viewBox 0 0 40 40, radius 16 like `SchemaVersionScoringPanel`). */
const GAUGE_R = 16;
const GAUGE_C = 2 * Math.PI * GAUGE_R;

interface CatalogLintPanelProps {
  /** The catalog item id to lint (a project id). */
  itemId: string;
  /** Whether the Lint tab is active; the report is fetched the first time this is true. */
  active: boolean;
  /** Opens the full `CatalogLintReportDialog` (the itemized report the orb opens — kept for history). */
  onOpenReport: () => void;
  /** Opens the quality-history dialog; disabled by the caller when there is no history/score. */
  onOpenQualityHistory: () => void;
  /** Whether a quality score/history exists (drives the history button's enabled state). */
  qualityAvailable: boolean;
  /**
   * The parsed-entity names rendered in the Overview tab (MFI-25.3). Entity-scoped findings whose
   * `path` resolves to one of these names become deep links (MFI-28.2). Absent/empty disables the
   * deep links (findings still render, just as plain text).
   */
  entityNames?: readonly string[];
  /** Follow an entity-scoped finding to its Overview entity (switch tab + scroll + highlight). */
  onNavigateToEntity?: (name: string) => void;
  /**
   * When the item was last written/scored (the detail's `updated_at`), shown in the provenance
   * strip. Optional — the strip omits the "Scored" row when it is absent.
   */
  scoredAt?: string | null;
}

/** The fetch lifecycle of the lint report (`idle`/`loading` render the spinner). */
type LintStatus = 'idle' | 'loading' | 'loaded' | 'error';

/** The severity chips shown in each fallback category bar, in severity order. */
const BREAKDOWN_SEGMENTS: readonly {
  key: keyof Pick<CategorySeverityBreakdown, 'error' | 'warning' | 'info'>;
  fillClass: string;
}[] = [
  { key: 'error', fillClass: 'bg-rose-500' },
  { key: 'warning', fillClass: 'bg-amber-500' },
  { key: 'info', fillClass: 'bg-sky-500' },
];

/**
 * The grade gauge: an SVG ring filled to `score`%, tinted by the score band, with the server letter
 * grade and `score/100` in the centre. Static (no mount animation) to stay trivially testable.
 */
function GradeGauge({ score, grade }: { score: number; grade: string }) {
  const tier = getNumericScoreTier(score);
  const letter = (grade || '').trim() || '–';
  return (
    <div className="flex flex-col items-center gap-3" data-testid="catalog-lint-gauge">
      <div className="relative h-32 w-32 shrink-0">
        <svg viewBox="0 0 40 40" className="h-full w-full -rotate-90" aria-hidden>
          <circle
            cx="20"
            cy="20"
            r={GAUGE_R}
            fill="none"
            className="stroke-gray-200 dark:stroke-gray-700"
            strokeWidth="3.5"
          />
          <circle
            cx="20"
            cy="20"
            r={GAUGE_R}
            fill="none"
            className={cn('stroke-current transition-all duration-500', tier.gaugeStrokeClass)}
            strokeWidth="3.5"
            strokeLinecap="round"
            strokeDasharray={GAUGE_C}
            strokeDashoffset={gaugeDashOffset(score, GAUGE_C)}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className={cn('font-mono text-3xl font-bold leading-none tabular-nums', tier.textClass)}
            data-testid="catalog-lint-gauge-grade"
          >
            {letter}
          </span>
          <span className="mt-1 font-mono text-[11px] tabular-nums text-gray-500 dark:text-gray-400">
            {score}/100
          </span>
        </div>
      </div>
      <span
        className={cn(
          'inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold',
          gradeChipClass(letter),
        )}
      >
        Grade {letter}
      </span>
      <span className="text-center text-[11px] text-gray-500 dark:text-gray-400">
        {tier.shortLabel} · deterministic lint
      </span>
    </div>
  );
}

/** A real per-category 0–100 score bar (MFI-25.6 data path). */
function CategoryScoreBar({ name, score }: { name: string; score: number }) {
  const tier = getNumericScoreTier(score);
  return (
    <div data-testid="catalog-lint-category-bar">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-gray-700 dark:text-gray-300">{humanizeCategory(name)}</span>
        <span className="font-mono tabular-nums text-gray-500 dark:text-gray-400">{score}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
        <div
          className={cn('h-full rounded-full transition-all duration-500', tier.barSolidClass)}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  );
}

/**
 * A fallback category bar: a severity-proportioned track (error/warning/info segments) plus the
 * per-severity counts. Used until real per-category scores (MFI-25.6) land.
 */
function CategoryBreakdownBar({ row }: { row: CategorySeverityBreakdown }) {
  return (
    <div data-testid="catalog-lint-category-breakdown">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-gray-700 dark:text-gray-300">{humanizeCategory(row.category)}</span>
        <span className="flex items-center gap-1.5 font-mono tabular-nums text-gray-500 dark:text-gray-400">
          {BREAKDOWN_SEGMENTS.filter((s) => row[s.key] > 0).map((s) => (
            <span key={s.key}>
              {row[s.key]} {s.key}
            </span>
          ))}
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-700">
        {BREAKDOWN_SEGMENTS.map((s) =>
          row[s.key] > 0 ? (
            <div
              key={s.key}
              className={s.fillClass}
              style={{ width: `${(row[s.key] / row.total) * 100}%` }}
            />
          ) : null,
        )}
      </div>
    </div>
  );
}

/** One tile in the severity summary strip (count + label + caption). */
function SummaryTile({
  label,
  count,
  countClass,
  caption,
}: {
  label: string;
  count: number;
  /** Tint for a non-zero count (e.g. rose for MUST); zero stays neutral. */
  countClass?: string;
  caption: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          {label}
        </span>
        <span
          className={cn(
            'font-mono text-xl font-bold tabular-nums text-gray-900 dark:text-white',
            countClass,
          )}
        >
          {count}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">{caption}</p>
    </div>
  );
}

/** Format an ISO instant for the provenance strip, or `null` when absent/invalid. */
function formatScoredAt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return new Date(ms).toLocaleString();
}

/** One labelled cell in the provenance strip (a `<dt>`/`<dd>` pair). */
function ProvenanceCell({
  label,
  icon,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2">
      <dt className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
        {icon}
        {label}
      </dt>
      <dd className="min-w-0 text-xs text-gray-700 dark:text-gray-300">{children}</dd>
    </div>
  );
}

/**
 * The report provenance strip (MFI-28.2): the version label, when it was scored, whether the score
 * is the stored one or a live recompute, and the report fingerprint — mirroring the MCP Lint & Score
 * header so both surfaces read the same.
 */
function ProvenanceStrip({
  report,
  scoredAt,
}: {
  report: VersionLintReport;
  scoredAt?: string | null;
}) {
  const provenance = catalogLintProvenance(report);
  const scored = formatScoredAt(scoredAt);
  return (
    <dl
      data-testid="catalog-lint-provenance"
      className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-gray-200 bg-gray-50/60 px-4 py-2.5 dark:border-gray-700 dark:bg-gray-900/30"
    >
      <ProvenanceCell label="Version">
        <span className="font-mono text-gray-900 dark:text-white">{report.versionId}</span>
      </ProvenanceCell>
      {scored ? (
        <ProvenanceCell label="Scored" icon={<Clock className="h-3 w-3" aria-hidden />}>
          {scored}
        </ProvenanceCell>
      ) : null}
      <ProvenanceCell label="Source">
        <span
          data-testid="catalog-lint-provenance-source"
          className={cn(
            'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold',
            provenance.stale
              ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
              : 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',
          )}
          title="Whether the score shown is the one persisted at import or a live recompute"
        >
          {provenance.stale ? <AlertTriangle className="h-3 w-3" aria-hidden /> : null}
          {provenance.label}
        </span>
      </ProvenanceCell>
      {report.reportFingerprint ? (
        <ProvenanceCell label="Fingerprint" icon={<Fingerprint className="h-3 w-3" aria-hidden />}>
          <span
            className="block max-w-[10rem] truncate font-mono text-gray-500 dark:text-gray-400"
            title={`Report fingerprint: ${report.reportFingerprint}`}
          >
            {report.reportFingerprint}
          </span>
        </ProvenanceCell>
      ) : null}
    </dl>
  );
}

/**
 * One finding row inside a tier section: rule + message, and the `path` rendered as a deep link to
 * its Overview entity when the path resolves to a known parsed entity (MFI-28.2), else plain text.
 */
function FindingRow({
  finding,
  rowClass,
  entityName,
  onNavigateToEntity,
}: {
  finding: VersionLintFinding;
  rowClass: string;
  /** The parsed entity this finding resolves to, or `null` when it is not entity-scoped. */
  entityName: string | null;
  onNavigateToEntity?: (name: string) => void;
}) {
  const linkable = entityName != null && !!onNavigateToEntity;
  return (
    <li className={cn('rounded-lg p-3', rowClass)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[11px] text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
          {finding.rule}
        </span>
        {finding.path ? (
          linkable ? (
            <button
              type="button"
              data-testid="catalog-lint-finding-link"
              onClick={() => onNavigateToEntity!(entityName!)}
              className="inline-flex items-center gap-1 font-mono text-[11px] font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              title={`Jump to ${entityName} in Overview`}
            >
              {finding.path}
              <ArrowUpRight className="h-3 w-3" aria-hidden />
            </button>
          ) : (
            <span className="font-mono text-[11px] text-gray-400 dark:text-gray-500">
              {finding.path}
            </span>
          )
        ) : null}
      </div>
      <p className="mt-1 text-sm text-gray-700 dark:text-gray-200">{finding.message}</p>
    </li>
  );
}

/** One requirement-tier section (MUST / SHOULD / advisory) with its per-tier count + findings. */
function TierSection({
  meta,
  findings,
  resolveEntity,
  onNavigateToEntity,
}: {
  meta: CatalogLintTierMeta;
  findings: VersionLintFinding[];
  /** Resolve a finding to the parsed-entity name it flags (or `null`). */
  resolveEntity: (finding: VersionLintFinding) => string | null;
  onNavigateToEntity?: (name: string) => void;
}) {
  return (
    <section data-testid={`catalog-lint-tier-${meta.key}`}>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h4 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide',
              meta.badgeClass,
            )}
          >
            {meta.label}
            <span
              data-testid={`catalog-lint-tier-count-${meta.key}`}
              className="tabular-nums"
            >
              {findings.length}
            </span>
          </span>
        </h4>
        <p className="text-xs text-gray-500 dark:text-gray-400">{meta.description}</p>
      </div>
      <ul className="space-y-2">
        {findings.map((f) => (
          <FindingRow
            key={f.id}
            finding={f}
            rowClass={meta.rowClass}
            entityName={resolveEntity(f)}
            onNavigateToEntity={onNavigateToEntity}
          />
        ))}
      </ul>
    </section>
  );
}

/**
 * Render a catalog item's lint report inline: grade gauge, category bars, and findings list.
 * Fetches lazily on first activation of the Lint tab and exposes a retry on failure.
 */
export function CatalogLintPanel({
  itemId,
  active,
  onOpenReport,
  onOpenQualityHistory,
  qualityAvailable,
  entityNames,
  onNavigateToEntity,
  scoredAt,
}: CatalogLintPanelProps) {
  const [status, setStatus] = useState<LintStatus>('idle');
  const [report, setReport] = useState<VersionLintReport | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Guards the one-shot lazy fetch so re-activating the tab never re-fetches.
  const fetchStartedRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // Lazy + one-shot fetch of the lint report. The guard (active + not-yet-started) sits at the top,
  // before any setState, so the effect stays a single `void` call with no synchronous cascading
  // render (mirrors CatalogSourceViewer). `retry` re-opens the one-shot by clearing the ref.
  const loadReport = useCallback(async () => {
    if (!active || fetchStartedRef.current) return;
    fetchStartedRef.current = true;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setErrorMessage(null);
    // Resolve into locals and commit the outcome once in `finally`, so the fetch drives a single
    // terminal state transition (loaded/error) rather than several branch-by-branch setState calls.
    let loadedReport: VersionLintReport | null = null;
    let failureMessage: string | null = null;
    try {
      loadedReport = await fetchCatalogLintReport(itemId, { signal: controller.signal });
    } catch (e) {
      failureMessage = e instanceof Error ? e.message : 'Failed to load lint report.';
    } finally {
      if (controller.signal.aborted) {
        /* superseded by a newer fetch/unmount — leave state to the newer run. */
      } else if (failureMessage != null) {
        setErrorMessage(failureMessage);
        setStatus('error');
      } else {
        setReport(loadedReport);
        setStatus('loaded');
      }
    }
  }, [active, itemId]);

  useEffect(() => {
    void loadReport();
  }, [loadReport]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Retry from the error affordance — an event handler, so re-opening the one-shot and re-running
  // the fetch synchronously is fine.
  const retry = useCallback(() => {
    fetchStartedRef.current = false;
    void loadReport();
  }, [loadReport]);

  const findings = report ? sortLintFindings(report.findings) : [];
  const categoryScores = resolveCategoryScores(report);
  const breakdown = report ? deriveCategorySeverityBreakdown(report.findings) : [];
  // Severity tallies for the summary strip (error → MUST, warning → SHOULD, info → advisory).
  const mustCount = findings.filter((f) => f.severity === 'error').length;
  const shouldCount = findings.filter((f) => f.severity === 'warning').length;
  const advisoryCount = findings.length - mustCount - shouldCount;
  const rulesTriggered = new Set(findings.map((f) => f.rule)).size;
  // Findings grouped into MUST/SHOULD/advisory tier sections (MFI-28.2), empty tiers dropped.
  const tierGroups = catalogLintGroupByTier(findings).filter((g) => g.findings.length > 0);

  // Deep-link resolution: a finding's `path` links to its Overview entity when it names a known
  // parsed entity. The name set is memoized so it is rebuilt only when the entity list changes.
  const entityNameSet = useMemo(() => new Set(entityNames ?? []), [entityNames]);
  const resolveEntity = useCallback(
    (finding: VersionLintFinding) => resolveCatalogFindingEntity(finding.path, entityNameSet),
    [entityNameSet],
  );

  return (
    <section className={`${dashboardPanelClass} p-6`} data-testid="catalog-detail-lint">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Lint &amp; score
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-testid="catalog-detail-quality-history"
            onClick={onOpenQualityHistory}
            disabled={!qualityAvailable}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-white dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700 dark:disabled:hover:bg-gray-800"
          >
            <History className="h-4 w-4 text-indigo-500" /> Quality history
          </button>
          <button
            type="button"
            data-testid="catalog-detail-lint-report"
            onClick={onOpenReport}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            <FileSearch className="h-4 w-4 text-indigo-500" /> Open full report
          </button>
        </div>
      </div>

      {status === 'idle' || status === 'loading' ? (
        <p
          data-testid="catalog-lint-loading"
          className="mt-6 text-sm text-gray-500 dark:text-gray-400"
        >
          Loading lint report…
        </p>
      ) : status === 'error' ? (
        <div
          data-testid="catalog-lint-error"
          className="mt-6 flex flex-col items-start gap-3 rounded-xl border border-rose-200 bg-rose-50/60 p-4 text-sm dark:border-rose-900 dark:bg-rose-950/30"
        >
          <span className="flex items-center gap-2 text-rose-700 dark:text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
            {errorMessage || 'Failed to load lint report.'}
          </span>
          <button
            type="button"
            data-testid="catalog-lint-retry"
            onClick={retry}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            <RefreshCw className="h-4 w-4" /> Retry
          </button>
        </div>
      ) : report ? (
        <>
        {/* Report provenance (MFI-28.2): version, scored-at, stored-vs-computed, fingerprint. */}
        <ProvenanceStrip report={report} scoredAt={scoredAt} />

        {/* Severity summary strip: MUST / SHOULD / advisory tallies + distinct rules triggered, so
            the report's weight is readable at a glance before the gauge/category/finding detail. */}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="catalog-lint-summary">
          <SummaryTile
            label="MUST"
            count={mustCount}
            countClass={mustCount > 0 ? 'text-rose-600 dark:text-rose-400' : undefined}
            caption="Hard requirements (errors)"
          />
          <SummaryTile
            label="SHOULD"
            count={shouldCount}
            countClass={shouldCount > 0 ? 'text-amber-600 dark:text-amber-400' : undefined}
            caption="Recommendations (warnings)"
          />
          <SummaryTile label="Advisory" count={advisoryCount} caption="Informational notes" />
          <SummaryTile
            label="Rules triggered"
            count={rulesTriggered}
            caption="Distinct lint rules with findings"
          />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
          {/* Grade gauge */}
          <div className="flex flex-col items-center justify-center rounded-xl border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-800">
            <GradeGauge score={report.score} grade={report.grade} />
          </div>

          {/* Category bars + findings */}
          <div className="min-w-0 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
            <div data-testid="catalog-lint-categories">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
                Categories
              </h3>
              {categoryScores ? (
                <div className="mt-3 space-y-3">
                  {categoryScores.map((c) => (
                    <CategoryScoreBar key={c.name} name={c.name} score={c.score} />
                  ))}
                </div>
              ) : breakdown.length > 0 ? (
                <>
                  <div className="mt-3 space-y-3">
                    {breakdown.map((row) => (
                      <CategoryBreakdownBar key={row.category} row={row} />
                    ))}
                  </div>
                  <p className="mt-3 text-[11px] text-gray-400 dark:text-gray-500">
                    Severity breakdown by category — per-category 0–100 scores arrive with the lint
                    rollup enrichment (MFI-25.6).
                  </p>
                </>
              ) : (
                <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">
                  No category findings.
                </p>
              )}
            </div>

            <h3 className="mt-6 text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Findings
            </h3>
            {findings.length === 0 ? (
              <p
                data-testid="catalog-lint-no-findings"
                className="mt-3 text-sm text-gray-600 dark:text-gray-300"
              >
                No findings — clean bill of health.
              </p>
            ) : (
              // Findings grouped into MUST/SHOULD/advisory tier sections (MFI-28.2). Each finding's
              // `path` deep-links to its Overview entity when it resolves to a parsed entity.
              <div className="mt-3 space-y-6" data-testid="catalog-lint-findings">
                {tierGroups.map((group) => (
                  <TierSection
                    key={group.meta.key}
                    meta={group.meta}
                    findings={group.findings}
                    resolveEntity={resolveEntity}
                    onNavigateToEntity={onNavigateToEntity}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
        </>
      ) : null}
    </section>
  );
}
