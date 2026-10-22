'use client';

/**
 * The posture facts line (HIVE-11.10, #5606).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` annotation 2 and
 * `docs/mockups/PROPOSALS.md` finding 1. Lint posture used to open with four stat tiles and a
 * grades/axes card (≈ 240 px) before its saved views and the queue. The same four figures now
 * read as one line — `0 unwaived security errors · 2 of 12 subjects missing coverage · 5 new
 * findings · 1 active waiver` — followed by the A–F grade chips, and the full
 * {@link LintPostureSummary} (tiles, grades, axis scores) is one **Show stats** click away,
 * revealed in place and remembered per device under `hive.lint-posture.stats`.
 *
 * ### Every fact is still a drill-down
 *
 * Each figure is a `<button>` that runs its tile's canned filter, with the tile's hint as its
 * tooltip — folding the strip must not cost the one thing the tiles did. Unwaived security
 * errors above zero is a `danger` chip, as the tile's *Needs attention* callout was.
 */

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { FactsLine, type FactsLineFact } from '@/app/components/ui/FactsLine';
import type { LintWorkspaceSummary } from '@/app/utils/lint-workspace';
import { cn } from '@lib/utils';

import LintPostureSummary, { LintGradeChip } from './LintPostureSummary';
import { postureFactGrades, postureFacts, type PostureDrillTarget } from './lintWorkspaceModel';

/** Props for {@link LintPostureFactsLine}. */
export interface LintPostureFactsLineProps {
  /** The posture summary, or `null` while it is being read (or when the read failed). */
  summary: LintWorkspaceSummary | null;
  /** True while the summary read is in flight. */
  loading?: boolean;
  /** Jump the queue to a fact's canned filter. */
  onDrillDown: (target: PostureDrillTarget) => void;
}

/**
 * Render the line.
 *
 * @param props See {@link LintPostureFactsLineProps}.
 * @returns The facts line with the full summary behind **Show stats**; a skeleton line while
 *   loading; nothing when the summary read failed — the queue is the page's substance.
 */
export default function LintPostureFactsLine({
  summary,
  loading = false,
  onDrillDown,
}: LintPostureFactsLineProps) {
  if (!summary && !loading) return null;

  const facts: FactsLineFact[] = summary
    ? postureFacts(summary).map((fact) => ({
        id: fact.target,
        // No `value`: the figure rides inside the button, so the whole fact is one target.
        label: (
          <button
            type="button"
            className={cn('lw-fact', fact.alert && 'lw-fact--alert')}
            title={fact.drillHint}
            onClick={() => onDrillDown(fact.target)}
            data-testid={`posture-fact-${fact.target}`}
          >
            {fact.alert ? <AlertTriangle aria-hidden /> : null}
            <b>{fact.value}</b> {fact.label}
          </button>
        ),
      }))
    : [];

  if (summary) {
    facts.push({
      id: 'grades',
      label: (
        <span className="lw-fact-grades" data-testid="posture-fact-grades">
          <span className="sr-only">Grades:</span>
          {postureFactGrades(summary).map((grade) => (
            <LintGradeChip key={grade.key} grade={grade} />
          ))}
        </span>
      ),
    });
  }

  return (
    <FactsLine
      page="lint-posture"
      aria-label="Posture facts"
      facts={facts}
      loading={loading && !summary}
      stats={<LintPostureSummary summary={summary} loading={loading} onDrillDown={onDrillDown} />}
    />
  );
}
