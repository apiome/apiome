'use client';

import { Fragment } from 'react';
import {
  factsLine,
  factsLineText,
  type CardFacts,
  type FactItem,
  type FactKind,
} from '../../../lib/cardFacts';

/** Grade tones: A/B read as good, C as middling, D/F as a warning. */
const GRADE_TONE: Record<string, string> = {
  A: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/20',
  B: 'bg-sky-50 text-sky-700 ring-sky-600/20 dark:bg-sky-500/10 dark:text-sky-300 dark:ring-sky-400/20',
  C: 'bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20',
  D: 'bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-400/20',
  F: 'bg-rose-50 text-rose-700 ring-rose-600/20 dark:bg-rose-500/10 dark:text-rose-300 dark:ring-rose-400/20',
};

const PILL = 'inline-flex items-center rounded-full px-1.5 py-px text-[10.5px] font-semibold ring-1 ring-inset';
const AVAILABILITY_TONE =
  'bg-[var(--brand-soft)] text-[var(--brand-soft-text)] ring-[var(--brand)]/20';

/** The classes for one item: counts and dates are plain text, the rest are pills. */
function itemClasses(item: FactItem): string {
  switch (item.kind) {
    case 'grade':
      return `${PILL} ${GRADE_TONE[item.grade ?? ''] ?? GRADE_TONE.C}`;
    case 'mock':
    case 'sdk':
      return `${PILL} ${AVAILABILITY_TONE}`;
    case 'format':
      return `${PILL} bg-zinc-100 font-medium text-zinc-600 ring-zinc-500/10 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-400/10`;
    case 'operations':
    case 'schemas':
      return 'font-medium tabular-nums text-zinc-700 dark:text-zinc-200';
    case 'updated':
    default:
      return 'tabular-nums';
  }
}

/**
 * The compact facts line of a card, a header or a project search hit (BDX-2.2):
 * `42 operations · 18 schemas · Grade B · Mock · SDK · OpenAPI 3.1 · updated 3d ago`.
 *
 * Renders nothing when there is nothing to say, so a surface can pass whatever facts its row had.
 *
 * @param facts - The version's facts (from `pickCardFacts`).
 * @param omit - Facts the surface already states another way (a version header's mock badge).
 * @param size - `sm` on cards and hits, `md` in an entity header.
 * @param className - Extra layout classes from the parent.
 */
export function FactsLine({
  facts,
  omit,
  size = 'sm',
  className = '',
}: {
  facts: CardFacts | null | undefined;
  omit?: readonly FactKind[];
  size?: 'sm' | 'md';
  className?: string;
}) {
  const items = factsLine(facts, { omit });
  if (items.length === 0) return null;
  return (
    <p
      className={`flex flex-wrap items-center gap-x-1.5 gap-y-1 text-zinc-500 dark:text-zinc-400 ${
        size === 'md' ? 'text-[13px]' : 'text-[11px]'
      } ${className}`}
      title={factsLineText(items)}
      data-testid="facts-line"
    >
      {items.map((item, i) => (
        <Fragment key={item.kind}>
          {i > 0 && (
            <span aria-hidden="true" className="text-zinc-300 dark:text-zinc-700">
              ·
            </span>
          )}
          <span className={itemClasses(item)} title={item.title} data-fact={item.kind}>
            {item.label}
          </span>
        </Fragment>
      ))}
    </p>
  );
}
