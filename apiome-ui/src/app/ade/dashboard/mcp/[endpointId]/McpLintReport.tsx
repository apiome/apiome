"use client";

import * as Progress from "@radix-ui/react-progress";
import {
  ArrowUpRight,
  CheckCircle2,
  ClipboardList,
  Fingerprint,
  Gauge,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/app/components/ui/Badge";
import { LoadingState } from "@/app/components/ui/LoadingState";
import { EmptyState } from "@/app/components/ui/EmptyState";
import { GradeGlyph } from "@/app/components/ui/mcp/GradeGlyph";
import { FindingSeverity } from "@/app/components/ui/mcp/FindingSeverity";
import { dashboardPanelPaddedClass } from "@/app/components/ade/dashboard/dashboardScreenClasses";
import { getNumericScoreTier } from "@/app/utils/numeric-score-tier";
import {
  mcpLintCategoryBars,
  mcpLintFindingTarget,
  mcpLintGroupByTier,
  mcpLintTierCounts,
  type McpLintFinding,
  type McpLintReport,
  type McpLintTier,
} from "@/app/components/ade/dashboard/mcp/mcpLintUi";
import { lintAxisEvaluationFromLintReport } from "@/app/utils/lint-axis-ui";
import { LintAxisCoveragePanel } from "@/app/components/ade/dashboard/lint/LintAxisCoveragePanel";

/** Invoked when a finding links to its offending capability item (deep-link to the Capabilities tab). */
export type NavigateToItem = (itemType: string, name: string) => void;

/** A compact grade chip + MUST/SHOULD tallies, surfaced on the Overview section. */
export function McpGradeSummary({
  score,
  grade,
  mustCount,
  shouldCount,
}: {
  score: number | null;
  grade: string | null;
  mustCount: number;
  shouldCount: number;
}) {
  if (score === null) {
    return (
      <Badge variant="secondary" title="This version has not been scored yet">
        Unscored
      </Badge>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <GradeGlyph grade={grade} score={score} size="md" />
      {/* Tallies stay green when zero ("all clear"), so they keep the Badge primitive rather than
          the always-on FindingSeverity chip used for populated finding sections. */}
      <Badge variant={mustCount > 0 ? "error" : "success"} title="MUST findings (hard requirements)">
        {mustCount} MUST
      </Badge>
      <Badge variant={shouldCount > 0 ? "warning" : "secondary"} title="SHOULD findings (recommendations)">
        {shouldCount} SHOULD
      </Badge>
    </div>
  );
}

/** Format the report's scored-at instant for the header metadata; null-safe. */
function formatScoredAt(iso: string | null): string | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  return new Date(ms).toLocaleString();
}

/**
 * The report header: the grade gauge with its score-band label on the left, and the report's
 * provenance (version, scored-at, stored vs computed, fingerprint) on the right.
 */
function ReportHeader({ report }: { report: McpLintReport }) {
  const tier = getNumericScoreTier(report.score);
  const scoredAt = formatScoredAt(report.scored_at);
  const versionLabel = report.version_tag ?? `v${report.version_seq}`;
  return (
    <section className={dashboardPanelPaddedClass}>
      <div className="flex flex-wrap items-center justify-between gap-6">
        <div className="flex items-center gap-5">
          <GradeGlyph variant="gauge" size="lg" grade={report.grade} score={report.score} />
          <div className="min-w-0">
            <div className={`text-lg font-semibold ${tier.textClass}`}>
              {tier.shortLabel} — {tier.detailLabel}
            </div>
            <p className="mt-1 max-w-md text-sm text-gray-600 dark:text-gray-400">
              Deterministic quality score for this version&apos;s capability surface.{" "}
              {tier.rangeLabel} band.
            </p>
          </div>
        </div>
        <dl className="grid shrink-0 grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-1">
          <div className="flex items-center justify-between gap-6">
            <dt className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Version
            </dt>
            <dd className="font-medium text-gray-900 dark:text-white">{versionLabel}</dd>
          </div>
          {scoredAt ? (
            <div className="flex items-center justify-between gap-6">
              <dt className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                Scored
              </dt>
              <dd className="text-gray-700 dark:text-gray-300">{scoredAt}</dd>
            </div>
          ) : null}
          <div className="flex items-center justify-between gap-6">
            <dt className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Source
            </dt>
            <dd>
              <Badge variant="outline" title="Whether the report was served from persistence or scored live">
                {report.source === "stored" ? "Stored report" : "Computed live"}
              </Badge>
            </dd>
          </div>
          {report.report_fingerprint ? (
            <div className="flex items-center justify-between gap-6">
              <dt className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                <Fingerprint className="inline h-3.5 w-3.5" aria-hidden />
                <span className="sr-only">Fingerprint</span>
              </dt>
              <dd
                className="max-w-[10rem] truncate font-mono text-xs text-gray-500 dark:text-gray-400"
                title={`Report fingerprint: ${report.report_fingerprint}`}
              >
                {report.report_fingerprint}
              </dd>
            </div>
          ) : null}
        </dl>
      </div>
    </section>
  );
}

/** One tier tally tile (MUST / SHOULD / Advisory) for the summary strip. */
function TierStatTile({
  tier,
  count,
  caption,
}: {
  tier: McpLintTier;
  count: number;
  caption: string;
}) {
  return (
    <div className={dashboardPanelPaddedClass}>
      <div className="flex items-center justify-between gap-2">
        <FindingSeverity tier={tier} />
        <span className="text-2xl font-bold tabular-nums text-gray-900 dark:text-white">
          {count}
        </span>
      </div>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{caption}</p>
    </div>
  );
}

/** The MUST / SHOULD / Advisory / rules-triggered summary strip under the header. */
function SummaryTiles({ report }: { report: McpLintReport }) {
  const counts = mcpLintTierCounts(report.findings);
  const rulesTriggered = Object.keys(report.rule_hits).length;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <TierStatTile tier="must" count={counts.must} caption="Hard requirements — fix these to raise the grade." />
      <TierStatTile tier="should" count={counts.should} caption="Recommendations — address these to polish the surface." />
      <TierStatTile tier="advisory" count={counts.advisory} caption="Informational notes about the surface." />
      <div className={dashboardPanelPaddedClass}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
            Rules triggered
          </span>
          <span className="text-2xl font-bold tabular-nums text-gray-900 dark:text-white">
            {rulesTriggered}
          </span>
        </div>
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
          Distinct lint rules with at least one finding.
        </p>
      </div>
    </div>
  );
}

/** The per-category count bars (naming / structure / annotations / …), tinted by worst severity. */
function CategoryBars({ findings }: { findings: McpLintFinding[] }) {
  const bars = mcpLintCategoryBars(findings);
  if (bars.length === 0) return null;
  return (
    <section className={dashboardPanelPaddedClass}>
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
        <Gauge className="h-4 w-4 text-indigo-500" aria-hidden />
        Findings by category
      </h3>
      <div className="space-y-3">
        {bars.map((bar) => (
          <div key={bar.category}>
            <div className="mb-1 flex items-center justify-between gap-2 text-xs">
              <span className="font-medium text-gray-700 dark:text-gray-300">{bar.label}</span>
              <span className="text-gray-500 dark:text-gray-400 tabular-nums">{bar.count}</span>
            </div>
            <Progress.Root
              className="relative h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
              value={bar.percent}
            >
              <Progress.Indicator
                className={`h-full rounded-full ${bar.barClass} transition-transform duration-300`}
                style={{ transform: `translateX(-${100 - bar.percent}%)` }}
              />
            </Progress.Root>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One color-coded finding row, linking to its offending capability item when resolvable. */
function FindingRow({
  finding,
  rowClass,
  onNavigateToItem,
}: {
  finding: McpLintFinding;
  rowClass: string;
  onNavigateToItem?: NavigateToItem;
}) {
  const target = mcpLintFindingTarget(finding.path);
  return (
    <div className={`rounded-md p-3 ${rowClass}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-xs text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
          {finding.rule}
        </span>
        {target && onNavigateToItem ? (
          <button
            type="button"
            onClick={() => onNavigateToItem(target.item_type, target.name)}
            className="inline-flex items-center gap-1 font-mono text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            title={`Jump to ${finding.path} in Capabilities`}
          >
            {finding.path}
            <ArrowUpRight className="h-3 w-3" aria-hidden />
          </button>
        ) : (
          <span className="font-mono text-xs text-gray-700 dark:text-gray-300">{finding.path}</span>
        )}
      </div>
      <p className="mt-1 text-sm text-gray-700 dark:text-gray-200">{finding.message}</p>
    </div>
  );
}

/** One requirement-tier section (MUST / SHOULD / advisory) with its findings. */
function TierSection({
  tier,
  description,
  rowClass,
  findings,
  onNavigateToItem,
}: {
  tier: McpLintTier;
  description: string;
  rowClass: string;
  findings: McpLintFinding[];
  onNavigateToItem?: NavigateToItem;
}) {
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
          <FindingSeverity tier={tier} count={findings.length} />
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400">{description}</p>
      </div>
      <div className="space-y-2">
        {findings.map((finding) => (
          <FindingRow
            key={finding.id}
            finding={finding}
            rowClass={rowClass}
            onNavigateToItem={onNavigateToItem}
          />
        ))}
      </div>
    </section>
  );
}

interface Props {
  report: McpLintReport | null;
  loading: boolean;
  error: string | null;
  /** Deep-link a finding to its offending capability item on the Capabilities tab. */
  onNavigateToItem?: NavigateToItem;
}

/**
 * The "Lint & Score" tab: a report header (gauge + provenance), a MUST/SHOULD/advisory summary
 * strip, per-category count bars beside the itemized findings, each finding linking to the
 * capability item it flags. Presentational — the report is fetched by the parent so the same data
 * drives the Overview grade summary.
 */
export default function McpLintReport({ report, loading, error, onNavigateToItem }: Props) {
  if (loading) {
    return <LoadingState minHeightClassName="min-h-[220px]" message="Loading lint report…" />;
  }
  if (error || !report) {
    return (
      <EmptyState
        variant="compact"
        icon={<ShieldCheck className="h-8 w-8 text-white" aria-hidden />}
        title="Lint report unavailable"
        description={
          error ??
          "This endpoint has no scored version yet. Run discovery to capture a quality report."
        }
      />
    );
  }

  const tierGroups = mcpLintGroupByTier(report.findings);
  const clean = report.findings.length === 0;
  const axisEvaluation = lintAxisEvaluationFromLintReport({
    algorithmId: report.algorithm_id,
    axes: report.axes ?? undefined,
    compositeScore: report.composite_score,
    compositeGrade: report.composite_grade,
    requiredCoverageMet: report.required_coverage_met,
    reportFingerprint: report.report_fingerprint,
  });

  return (
    <div className="space-y-6">
      <ReportHeader report={report} />
      <SummaryTiles report={report} />
      {axisEvaluation ? <LintAxisCoveragePanel evaluation={axisEvaluation} /> : null}

      {clean ? (
        <section className={dashboardPanelPaddedClass}>
          <EmptyState
            variant="compact"
            icon={<CheckCircle2 className="h-8 w-8 text-white" aria-hidden />}
            title="No findings"
            description="This version's surface passes every lint rule — a clean bill of health."
          />
        </section>
      ) : (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-3">
          <div className="lg:sticky lg:top-4">
            <CategoryBars findings={report.findings} />
          </div>

          <section className={`${dashboardPanelPaddedClass} lg:col-span-2`}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
              <ClipboardList className="h-4 w-4 text-indigo-500" aria-hidden />
              Findings
            </h3>
            <div className="space-y-6">
              {tierGroups
                .filter((group) => group.findings.length > 0)
                .map((group) => (
                  <TierSection
                    key={group.meta.key}
                    tier={group.meta.key}
                    description={group.meta.description}
                    rowClass={group.meta.rowClass}
                    findings={group.findings}
                    onNavigateToItem={onNavigateToItem}
                  />
                ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
