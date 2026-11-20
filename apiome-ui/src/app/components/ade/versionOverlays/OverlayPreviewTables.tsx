'use client';

/**
 * The overlay manager's preview tables — COA-2.7 (#7050).
 *
 * * {@link OverlayActionsTable} — every action of the rendered chain: its overlay, kind, target and
 *   how many nodes the target matched (an action that matched nothing, or was refused, is flagged).
 * * {@link OverlayDiffTable} — every value the chain changed, before (the revision's source) and
 *   after, with the overlay action(s) that changed it: the value's provenance.
 *
 * Both read the preview reply as is, so they show exactly what an export renders.
 */

import { Badge } from '@/app/components/ui/Badge';

import {
  ACTION_KIND_LABEL,
  changedByLabel,
  formatDiffValue,
  matchSummary,
  matchTone,
  type OverlayActionKind,
} from './overlayDraftModel';
import type { OverlayActionOutcome, OverlayDiffRow } from './versionOverlaysApi';

/** Badge variant per match tone. */
const TONE_VARIANT = { ok: 'outline', warn: 'warn', danger: 'danger' } as const;

/** The readable name of an outcome's kind (`Reusable · tag-partner` for a reference). */
function kindLabel(outcome: OverlayActionOutcome): string {
  const label = ACTION_KIND_LABEL[outcome.kind as OverlayActionKind] ?? 'Unknown';
  return outcome.ref ? `${label} · ${outcome.ref}` : label;
}

/** The overlay's name without its report prefix (`stored:` / `draft:`). */
function overlayName(label: string): string {
  return label.replace(/^(stored|draft):/, '');
}

/**
 * A badge with an action's match count.
 *
 * @param props.outcome The action's outcome.
 * @returns The badge.
 */
export function MatchBadge({ outcome }: { outcome: OverlayActionOutcome }) {
  return (
    <Badge variant={TONE_VARIANT[matchTone(outcome)]} data-testid={`overlay-match-${outcome.action_index}`}>
      {matchSummary(outcome)}
    </Badge>
  );
}

/**
 * Every action the chain ran, with its match count.
 *
 * @param props.actions The report's `actions`.
 * @returns The table, or nothing when there are no rows.
 */
export function OverlayActionsTable({ actions }: { actions: readonly OverlayActionOutcome[] }) {
  if (actions.length === 0) return null;
  return (
    <div className="xstd-overlay__ledger">
      <table className="xstd-outcomes" data-testid="overlay-actions-table">
        <caption className="vovl-caption">Actions and matches</caption>
        <thead>
          <tr>
            <th scope="col">Overlay</th>
            <th scope="col">Action</th>
            <th scope="col">Target</th>
            <th scope="col">Matches</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((outcome) => (
            <tr key={`${outcome.overlay}-${outcome.action_index}`}>
              <td>{overlayName(outcome.overlay)}</td>
              <td>
                {outcome.action_index + 1}. {kindLabel(outcome)}
              </td>
              <td className="xstd-mono">{outcome.target || '—'}</td>
              <td>
                <MatchBadge outcome={outcome} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Every value the chain changed, before and after, and who changed it.
 *
 * @param props.rows The preview's `diff`.
 * @returns The table, or a note when nothing changed.
 */
export function OverlayDiffTable({ rows }: { rows: readonly OverlayDiffRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="xstd-empty" data-testid="overlay-diff-empty">
        The overlays change no values.
      </p>
    );
  }
  return (
    <div className="xstd-overlay__ledger">
      <table className="xstd-outcomes" data-testid="overlay-diff-table">
        <caption className="vovl-caption">Before and after</caption>
        <thead>
          <tr>
            <th scope="col">Value</th>
            <th scope="col">Before</th>
            <th scope="col">After</th>
            <th scope="col">Changed by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.pointer} data-kind={row.kind}>
              <td className="xstd-mono">{row.pointer || '/'}</td>
              <td className="vovl-diff__before">
                <span className="xstd-mono">{formatDiffValue(row.before, row.before_present)}</span>
              </td>
              <td className="vovl-diff__after">
                <span className="xstd-mono">{formatDiffValue(row.after, row.after_present)}</span>
              </td>
              <td>{changedByLabel(row)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
